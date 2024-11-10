import json
import logging
import os
import re
import socket
import time
import urllib.parse
from base64 import b64encode
from hashlib import sha256
from uuid import uuid4

import gevent
import prometheus_client as prom
import requests
import urllib3.connection
from gevent.pool import Pool
from ipaddress import ip_address

from . import atomic_write, ensure_directory, jitter, listdir
from .stats import timed


# Lots of things will tell you to go away if you don't look like a browser
# (eg. imgur)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


media_bytes_downloaded = prom.Counter(
	"media_bytes_downloaded",
	"Number of bytes of media files downloaded. Includes data downloaded then later rejected.",
)

media_bytes_saved = prom.Histogram(
	"media_bytes_saved",
	"Size in bytes of downloaded media that was successfully saved",
	["content_type"],
	buckets = [2**n for n in range(11, 27, 2)],
)

media_already_exists = prom.Counter(
	"media_already_exists",
	"Count of times we downloaded a file but it already existed",
)


class Rejected(Exception):
	"""Indicates a non-retryable failure due to the url response violating our constraints"""

class TooLarge(Rejected):
	"""Response was too large"""

class ForbiddenDestination(Rejected):
	"""Hostname resolved to non-global IP"""

class BadScheme(Rejected):
	"""Bad url scheme"""

class WrongContent(Rejected):
	"""Response was not a video or image"""

class FailedResponse(Rejected):
	"""Got a 4xx response, probably a bad link"""


def check_for_media(output_dir, url):
	"""Returns True if we have at least one version of content for the given url already."""
	url_dir = get_url_dir(output_dir, url)
	return any(filename.endswith(".metadata.json") for filename in listdir(url_dir))


@timed()
def download_media(
	url,
	output_dir,
	max_size=128*2**20, # 128MiB
	timeout=60,
	content_types=("image", "video", "application/pdf"),
	max_redirects=5,
	retries=3,
	retry_interval=1,
	chunk_size=64*1024, # 64KiB
):
	"""Make a GET request to a potentially malicious URL and download the content to file.
	We check the following:
	- That the host is a public IP
	- That the response does not exceed given max size (default 128MB)
	- That the content type is in the given list
	  (the list may contain exact types like "image/png" or categories like "image")
	- That the whole thing doesn't take more than a timeout
	Redirects *will* be followed but the follow-up requests must obey the same rules
	(and do not reset the timeout).

	We save the file to OUTPUT_DIR/URL_HASH/FILE_HASH.EXT where EXT is gussed from content-type.
	We save additional metadata including the url and content type to OUTPUT_DIR/URL_HASH/FILE_HASH.metadata.json

	Raises on any rule violation or non-200 response.
	"""
	# Stores a list of urls redirected to, latest is current.
	urls = [url]

	with gevent.Timeout(timeout):
		for redirect_number in range(max_redirects):
			errors = []
			for retry in range(retries):
				if retry > 0:
					gevent.sleep(jitter(retry_interval))

				try:
					if download_imgur_url(output_dir, max_size, url):
						return

					resp = _request(urls[-1], max_size, content_types)

					new_url = resp.get_redirect_location()
					if new_url:
						urls.append(resolve_relative_url(urls[-1], new_url))
						break # break from retry loop, continuing in the redirect loop

					_save_response(output_dir, urls, resp, max_size, chunk_size)
					return
				except Rejected:
					raise
				except Exception as e:
					errors.append(e)
					# fall through to next retry loop
			else:
				# This block will be reached if range(retries) runs out but not via "break"
				raise Exception(f"All retries failed for url {urls[-1]}: {errors}")

		raise Exception("Too many redirects")


def resolve_relative_url(base_url, url):
	"""As per RFC1808 Section 4"""
	base_parsed = urllib.parse.urlparse(base_url)
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme:
		# absolute url
		return url
	parsed = parsed._replace(scheme=base_parsed.scheme)
	if parsed.netloc == "":
		parsed = parsed._replace(netloc=base_parsed.netloc)
		if not parsed.path.startswith("/"):
			# This logic is a bit weird, but we stop as soon as we reach a non-empty part
			for key in ("path", "params", "query"):
				if getattr(parsed, key) != "":
					break
				parsed._replace(**{key: getattr(base_parsed, key)})
			base_path = os.path.basename(base_parsed.path)
			path = os.path.normpath(os.path.join(base_path, parsed.path))
			parsed = parsed._replace(path=path)
	return parsed.geturl()


def hash_to_path(hash):
	return b64encode(hash.digest(), b"-_").decode().rstrip("=")


def get_url_dir(output_dir, url):
	return os.path.join(output_dir, hash_to_path(sha256(url.encode())))


def _save_response(output_dir, urls, resp, max_size, chunk_size):
	url_dir = get_url_dir(output_dir, urls[0])
	temp_path = os.path.join(url_dir, f".{uuid4()}.temp")
	ensure_directory(temp_path)

	content_type = resp.headers["content-type"]
	# Content type may have form "TYPE ; PARAMS", strip params if present.
	# Also normalize for whitespace and case.
	content_type = content_type.split(";")[0].strip().lower()
	# We attempt to convert content type to an extension by taking the second part
	# and stripping anything past the first character not in [a-z0-9-].
	# So eg. "image/png" -> "png", "image/svg+xml" -> "svg", "image/../../../etc/password" -> ""
	ext = content_type.split("/")[-1]
	ext = re.match(r"^[a-z0-9.-]*", ext).group(0)

	try:
		length = 0
		hash = sha256()
		with open(temp_path, "wb") as f:
			while True:
				chunk = resp.read(chunk_size)
				if not chunk:
					break
				hash.update(chunk)
				length += len(chunk)
				media_bytes_downloaded.inc(len(chunk))
				if length > max_size:
					raise TooLarge(f"Read more than {length} bytes from url {urls[-1]}")
				f.write(chunk)

		filename = f"{hash_to_path(hash)}.{ext}"
		filepath = os.path.join(url_dir, filename)
		# This is vulnerable to a race where two things create the file at once,
		# but that's fine since it will always have the same content. This is just an optimization
		# to avoid replacing the file over and over (and for observability)
		if os.path.exists(filepath):
			logging.info(f"Discarding downloaded file for {urls[0]} as it already exists")
			media_already_exists.inc()
		else:
			os.rename(temp_path, filepath)
			logging.info(f"Downloaded file for {urls[0]}")
			media_bytes_saved.labels(content_type).observe(length)
	finally:
		if os.path.exists(temp_path):
			os.remove(temp_path)

	metadata_path = os.path.join(url_dir, f"{hash_to_path(hash)}.metadata.json")
	# Again, this is racy but we don't care about double-writes.
	# Note it's entirely possible for the image to already exist but still write the metadata,
	# this can happen if a previous attempt crashed midway.
	if not os.path.exists(metadata_path):
		metadata = {
			"url": urls[0],
			"filename": filename,
			"redirects": urls[1:],
			"content_type": resp.headers["content-type"],
			"fetched_by": socket.gethostname(),
			"fetch_time": time.time(),
		}
		atomic_write(metadata_path, json.dumps(metadata, indent=4))


def _save_content(output_dir, urls, ext, content):
	"""Alternate version of _save_response() for cases where content is explicitly generated
	instead of coming from a response."""
	url_dir = get_url_dir(output_dir, urls[0])
	if isinstance(content, str):
		content = content.encode()
	hash = sha256(content)
	filename = f"{hash_to_path(hash)}.{ext}"
	filepath = os.path.join(url_dir, filename)
	if not os.path.exists(filepath):
		atomic_write(filepath, content)
	metadata_path = os.path.join(url_dir, f"{hash_to_path(hash)}.metadata.json")
	if not os.path.exists(metadata_path):
		metadata = {
			"url": urls[0],
			"filename": filename,
			"redirects": urls[1:],
			"fetched_by": socket.gethostname(),
			"fetch_time": time.time(),
		}
		atomic_write(metadata_path, json.dumps(metadata, indent=4))


def _request(url, max_size, content_types):
	"""Do the actual request and return a vetted response object, which is either the content
	(status 200) or a redirect.
	Raises Rejected if content fails checks, anything else should be considered retryable."""
	parsed = urllib.parse.urlparse(url)
	hostname = parsed.hostname
	port = parsed.port

	ip = socket.gethostbyname(hostname)
	if not ip_address(ip).is_global:
		raise ForbiddenDestination(f"Non-global IP {ip} for url {url}")

	# In order to provide the host/ip to connect to seperately from the URL,
	# we need to drop to a fairly low-level interface.
	if parsed.scheme == "http":
		conn = urllib3.connection.HTTPConnection(ip, port or 80)
	elif parsed.scheme == "https":
		conn = urllib3.connection.HTTPSConnection(
			ip, port or 443,
			assert_hostname = hostname,
			server_hostname = hostname,
		)
	else:
		raise BadScheme(f"Bad scheme {parsed.scheme!r} for url {url}")

	headers = {
		"User-Agent": USER_AGENT,
	}
	conn.request("GET", url, headers=headers, preload_content=False)
	resp = conn.getresponse()

	# Redirects do not require further checks
	if resp.get_redirect_location():
		return resp

	# 4xx errors are non-retryable, anything else is.
	# However 420 and 429 are "rate limit" errors, which should be retried.
	if 400 <= resp.status < 500 and resp.status not in (420, 429):
		raise FailedResponse(f"Url returned {resp.status} response: {url}")
	elif not (200 <= resp.status < 300):
		raise Exception(f"Url returned {resp.status} response: {url}")

	content_type = resp.getheader("content-type")
	if content_type is None:
		raise Exception(f"No content-type given for url {url}")
	if not any(content_type.startswith(target) for target in content_types):
		raise WrongContent(f"Disallowed content-type {content_type} for url {url}")

	# If length is known but too large, reject early
	length = resp.getheader("content-length")
	if length is not None:
		try:
			length = int(length)
		except ValueError:
			raise Exception(f"Invalid content length {length!r} for url {url}")
		if length > max_size:
			raise TooLarge(f"Content length {length} is too large for url {url}")

	return resp


def download_imgur_url(output_dir, max_size, url):
	"""Links to imgur require special handling to resolve the actual image.
	Handles URLs like the following:
		i.stack.imgur.com/ID.png
		imgur.com/ID
			These map to actual media and are stored in the usual way.
		imgur.com/a/ID
		imgur.com/gallery/ID
			These map to collections of media.
			Under the original URL we store a json file that lists imgur.com/ID urls
			of the contents of the collection. Those urls are then downloaded and stored
			in the usual way.
	Notably this function doesn't need to handle URLs like:
		i.imgur.com/ID.EXT
	as this is already a direct image link, so we can just use the normal handling.
	"""
	parsed = urllib.parse.urlparse(url)
	if parsed.hostname not in ("imgur.com", "i.stack.imgur.com"):
		# not an imgur link that needs special handling
		return False
	match = re.match(r"^/([^/.]+)(?:\.([a-z]+))?$", parsed.path)
	if match:
		id, ext = match.groups()
		if ext is None:
			# Try to get a video ("gif") first, if that 400s then get a png.
			try:
				download_imgur_image(output_dir, max_size, url, id, "mp4")
			except requests.HTTPError:
				download_imgur_image(output_dir, max_size, url, id, "png")
		else:
			download_imgur_image(output_dir, max_size, url, id, ext)
		return True
	elif parsed.path.startswith("/a/"):
		# paths look like /a/some-name-then-ID
		id = parsed.path.removeprefix("/a/").split("-")[-1]
		contents = download_imgur_album(url, parsed.path.removeprefix("/a/"))
	elif parsed.path.startswith("/gallery/"):
		contents = download_imgur_gallery(url, parsed.path.removeprefix("/gallery/"))
	else:
		# no match, treat like non-imgur link
		return False

	# Common part for albums and galleries
	pool = Pool(16)
	jobs = []
	for id, ext in contents:
		job = pool.spawn(download_imgur_image, output_dir, max_size, f"https://imgur.com/{id}", id, ext)
		jobs.append(job)
	gevent.wait(jobs)
	failed = [g.exception for g in jobs if g.exception is not None]

	# Save the album after trying to download things (so it will be retried until we get this far)
	# but only raise for image download errors after, so we at least know about everything that
	# succeeded.
	contents_urls = [f"https://imgur.com/{id}" for id, ext in contents]
	_save_content(output_dir, [url], "json", json.dumps(contents_urls))

	if failed:
		raise Exception(str(failed))

	return True


def imgur_request(url):
	resp = requests.get(url, allow_redirects=False, timeout=30, headers={
		"User-Agent": USER_AGENT,
	})
	if 300 <= resp.status_code < 400:
		# imgur redirects you if the resource is gone instead of 404ing, treat this as non-retryable
		raise Rejected(f"imgur returned redirect for {url!r}")
	# other errors are retryable
	resp.raise_for_status()
	return resp


def download_imgur_album(url, id):
	"""Fetch imgur album and return a list of (id, ext) contents"""
	url = f"https://api.imgur.com/post/v1/albums/{id}?client_id=546c25a59c58ad7&include=media,adconfig,account"
	data = imgur_request(url).json()
	result = []
	for item in data.get("media", []):
		result.append((item["id"], item["ext"]))
	return result


def download_imgur_gallery(url, id):
	"""Fetch imgur gallery and return a list of (id, ext) contents"""
	# The gallery JSON is contained in a <script> tag like this:
	# <script>window.postDataJSON=...</script>
	# where ... is a json string.
	html = imgur_request(f"https://imgur.com/gallery/{id}").text
	regex = r'<script>window.postDataJSON=("(?:[^"\\]|\\.)*")'
	match = re.search(regex, html)
	# If we can't find a match, assume we got served a 404 page instead.
	if not match:
		raise Rejected(f"Could not load gallery for {url!r}")
	data = match.group(1)
	data = data[1:-1].encode().decode("unicode-escape") # remove quotes and unescape contents
	data = json.loads(data)
	result = []
	for item in data.get("media", []):
		result.append((item["id"], item["ext"]))
	return result


def download_imgur_image(output_dir, max_size, url, id, ext):
	"""Fetch imgur image and save it as per download_media()"""
	image_url = f"https://i.imgur.com/{id}.{ext}"
	resp = imgur_request(image_url)
	_save_content(output_dir, [url, image_url], ext, resp.content)


if __name__ == '__main__':
	import argh
	def main(url, output_dir):
		download_media(url, output_dir)

	argh.dispatch_command(main)
