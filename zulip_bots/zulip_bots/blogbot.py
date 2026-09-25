
"""
Blogbot watches the desertbus.org website blog and for each post:
- Saves the content as JSON
- Downloads any attached images
- Posts it to zulip

By default it will assume any existing posts are already processed, and only processes
new posts after it has been started.
"""

import gevent.monkey
gevent.monkey.patch_all()

import difflib
import json
import logging
import os
from base64 import b64encode
from datetime import datetime
from hashlib import sha256

import argh

from common import atomic_write
from common import media
from common import zulip
from common import website

from .config import common_setup, get_config

def try_save_image(media_dir, url):
    if media_dir is None:
        return {"error": "no media dir given"}
    try:
        return {"path": media.download_media(url, media_dir)}
    except media.Rejected as e:
        return {"error": str(e)}

def md_time(timestamp):
	return f"<time:{timestamp}>"

def md_block(content, type=""):
	return "\n".join([f"```{type}", content, "```"])

def md_link(text, url):
	return f"[{text}]({url})"

def md_spoiler(title, content):
	return md_block(content, f"spoiler {title}")

def blog_to_md(event, post):
	title = "UNKNOWN"
	author = "UNKNOWN"
	date = "UNKNOWN"

	try:
		author = post["author"]
		date = md_time(post['published_at'])
		url = f"https://desertbus.org/{event['url']}?id={post['id']}"
		title = md_link(post['title'], url)
		md_content = website.block_to_md(post["description"])
	except Exception as e:
		logging.warning(f"Failed to parse blog post: {post}", exc_info=True)
		md_content = f"Parsing blog failed, please see logs: {e}"

	return "\n".join([
		f"Blog Post: {title}",
		f"Posted by {author} at {date}",
		md_block(md_content, type="quote"),
	])

def diff_blogs(post_a, post_b):
	"""Given two posts, returns markdown containing the formatted diff"""
	updated_old = post_a.get("updated_at", post_a.get("published_at"))
	updated_old = "UNKNOWN" if updated_old is None else md_time(updated_old)
	# only include keys we want in the diff
	post_a, post_b = [
		{key: post.get(key) for key in ("author", "title", "description")}
		for post in (post_a, post_b)
	]
	# format as 2-indent json
	lines_a, lines_b = [json.dumps(post, indent=2).split("\n") for post in (post_a, post_b)]

	# first two lines are "---" / "+++", we don't need them. n is context window size.
	diff = "\n".join(list(difflib.unified_diff(lines_a, lines_b, n=5, lineterm=""))[2:])

	return md_spoiler(f"Diff from previous edit at {updated_old}", md_block(diff, type="diff"))

def edit_to_md(event, prev_post, post):
	title = "UNKNOWN"
	updated = "UNKNOWN"

	try:
		url = f"https://desertbus.org/{event['url']}?id={post['id']}"
		title = md_link(post['title'], url)
		updated = md_time(post["updated_at"])
		diff = diff_blogs(prev_post, post)
	except Exception as e:
		logging.warning(f"Failed to parse blog edit: {prev_post}, {post}", exc_info=True)
		diff = f"Generating diff failed, please see logs: {e}"

	return "\n".join([
		f"Blog post {title} was updated at {updated}",
		diff,
		md_spoiler("Updated post", blog_to_md(event, post)),
	])

def find_images(post):
	def _find_images(block):
		if block["type"] == "image":
			yield block["attrs"]["url"]
		for child in block.get("content", []):
			yield from _find_images(child)
	yield from _find_images(post["description"])

def send_post(client, stream, topic, save_dir, event, post):
	content = blog_to_md(event, post)
	if save_dir is not None and "id" in post:
		prev_post = find_post(save_dir, post["id"], exclude=post)
		if prev_post is not None:
			content = edit_to_md(event, prev_post, post)
	client.send_to_stream(stream, topic, content)

def save_post(save_dir, media_dir, post):
	hash_content = json.dumps(post, sort_keys=True).encode()
	hash = b64encode(sha256(hash_content).digest(), b"-_").decode().rstrip("=")
	filename = f"{post['id']}-{hash}.json"
	filepath = os.path.join(save_dir, filename)
	if os.path.exists(filepath):
		return
	images = set(find_images(post))
	content = {
		"retrieved_at": datetime.utcnow().isoformat() + "Z",
		"images": {image: try_save_image(media_dir, image) for image in images},
		"post": post,
	}
	atomic_write(filepath, json.dumps(content) + "\n")

def find_post(save_dir, id, exclude=None):
	"""Find previously saved posts for the given id, returning most recent or None.
	Exclude the post you're trying to diff against, which may already be present in test mode.
	"""
	files = [filename for filename in os.listdir(save_dir) if filename.split("-")[0] == id]

	posts = [] # (sort key, post)
	for filename in files:
		path = os.path.join(save_dir, filename)
		try:
			with open(path) as f:
				post = json.load(f)
			if post["post"] == exclude:
				continue
			# sort by updated/posted, or if none have that, sort by retrieved time as fallback
			if "updated_at" in post["post"]:
				key = (1, post["post"]["updated_at"])
			elif "published_at" in post["post"]:
				key = (1, post["post"]["published_at"])
			else:
				key = (0, post["retrieved_at"])
		except Exception:
			logging.warning(f"Failed to load post file {path!r}", exc_info=True)
		else:
			posts.append((key, post["post"]))

	return max(posts)[1] if posts else None

def main(config_file, test=False, event_id=None, stream='bot-spam', topic='Blog Posts', save_dir=None, media_dir=None, metrics_port=8016):
	"""Post to zulip each new blog post.
	Will not post any posts that already exist, unless --test is given
	in which case it will print the most recent on startup."""
	common_setup(metrics_port)
	config = get_config(config_file)
	zulip_client = zulip.Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])

	webclient = website.Client(event_id=event_id)
	event = webclient.event()
	events = webclient.event_stream()
	events.subscribe_blog()

	# On startup, save all existing posts in case we missed any.
	# Note we do this *after* subscribing to avoid a race window.
	# Double-saving is fine.
	latest = None
	for post in webclient.blog_posts():
		if latest is None:
			latest = post
		if save_dir is not None:
			save_post(save_dir, media_dir, post)

	if test:
		if latest is None:
			logging.warning("Ignoring --test, no blog posts found")
		else:
			send_post(zulip_client, stream, topic, save_dir, event, latest)

	for message in events.recv():
		if message.event != "post":
			continue
		if save_dir is not None:
			save_post(save_dir, media_dir, message.payload)
		send_post(zulip_client, stream, topic, save_dir, event, message.payload)


if __name__ == '__main__':
	argh.dispatch_command(main)
