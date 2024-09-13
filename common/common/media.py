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
import urllib3.connection
from ipaddress import ip_address

from . import atomic_write, ensure_directory, jitter, listdir
from .stats import timed


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
	content_types=("image", "video"),
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
					resp = _request(urls[-1], max_size, content_types)

					new_url = resp.get_redirect_location()
					if new_url:
						urls.append(new_url)
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
				raise ExceptionGroup(f"All retries failed for url {urls[-1]}", errors)

		raise Exception("Too many redirects")


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

	conn.request("GET", url, preload_content=False)
	resp = conn.getresponse()

	# Redirects do not require further checks
	if resp.get_redirect_location():
		return resp

	if resp.status != 200:
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
