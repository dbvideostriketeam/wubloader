
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

import json
import logging
import os
import re
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

def blog_to_md(post):
	title = "UNKNOWN"
	author = "UNKNOWN"
	date = "UNKNOWN"

	try:
		title = post["title"]
		author = post["author"]
		date = f"<time:{post['published_at']}>"
		md_content = website.block_to_md(post["description"])
	except Exception as e:
		logging.warning(f"Failed to parse blog post: {post}", exc_info=True)
		md_content = f"Parsing blog failed, please see logs: {e}"

	return "\n".join([
		f"Blog Post: [{title}](https://desertbus.org/?id={id})",
		f"Posted by {author} at {date}",
		"```quote",
		md_content,
		"```",
	])

def find_images(post):
	def _find_images(block):
		if block["type"] == "image":
			yield block["attrs"]["url"]
		for child in block.get("content", []):
			yield from _find_images(child)
	yield from _find_images(post["description"])

def send_post(client, stream, topic, post):
	client.send_to_stream(stream, topic, blog_to_md(post))

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

def main(config_file, test=False, event_id=None, stream='bot-spam', topic='Blog Posts', save_dir=None, media_dir=None, metrics_port=8016):
	"""Post to zulip each new blog post.
	Will not post any posts that already exist, unless --test is given
	in which case it will print the most recent on startup."""
	common_setup(metrics_port)
	config = get_config(config_file)
	zulip_client = zulip.Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])

	webclient = website.Client(event_id=event_id)
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
			send_post(zulip_client, stream, topic, latest)

	for message in events.recv():
		if message.event != "post":
			continue
		if save_dir is not None:
			save_post(save_dir, media_dir, message.payload)
		send_post(zulip_client, stream, topic, message.payload)


if __name__ == '__main__':
	argh.dispatch_command(main)
