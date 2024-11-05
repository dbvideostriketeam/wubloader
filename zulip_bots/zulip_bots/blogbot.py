
import json
import logging
import os
import re
import time
from base64 import b64encode
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

import argh
import requests
import bs4
from bs4 import BeautifulSoup

from .zulip import Client
from .config import get_config

logging.basicConfig(level='INFO')

def html_to_md(html):
	"""Lossy attempt to convert html to markdown"""
	if isinstance(html, bs4.Comment):
		return ""

	if html.name is None:
		# Raw string, return as-is
		return html

	if html.name == "br":
		return "\n"

	if html.name == "hr":
		return "---"

	if html.name == "img":
		return html.get("src") + "\n"

	inner = "".join(html_to_md(child) for child in html.children)

	if html.name == "a":
		return "[{}]({})".format(inner, html.get("href"))

	if html.name == "p":
		return inner + "\n"

	if html.name == "li":
		return "\n* " + inner

	CHAR_FORMAT = {
		"b": "**",
		"strong": "**",
		"h1": "**",
		"h2": "**",
		"h3": "**",
		"h4": "**",
		"h5": "**",
		"h6": "**",
		"i": "*",
		"em": "*",
		"del": "~~",
		"pre": "`",
		"code": "`",
	}
	if html.name in CHAR_FORMAT:
		char = CHAR_FORMAT[html.name]
		return f"{char}{inner}{char}"

	return inner

def blog_to_md(id, html):
	title = "UNKNOWN"
	author = "UNKNOWN"
	date = "UNKNOWN"
	try:
		a = html.a
		authoring, content = html.find_all("div", recursive=False)

		title = a.string
		author_candidates = authoring.find_all(string=lambda v: v.startswith("Posted by"))
		if len(author_candidates) == 1:
			author = author_candidates[0]
		date_element = authoring.find("astro-island")
		if date_element is not None:
			try:
				props = json.loads(date_element["props"])
				timestamp = props["time"][1]
				date = f"<time:{timestamp}>"
			except Exception:
				pass # error determining date, ignore
		md_content = html_to_md(content)
	except Exception as e:
		md_content = f"Parsing blog failed, please see logs: {e}"

	return "\n".join([
		f"Blog Post: [{title}](https://desertbus.org/?id={id})",
		f"Posted by {author} at {date}",
		"```quote",
		md_content,
		"```",
	])

def get_posts():
	"""Get all blog posts on the front page as (id, html)"""
	# Need to clear UA or we get blocked due to "python" in UA
	resp = requests.get("https://desertbus.org/2024/", headers={"User-Agent": ""})
	resp.raise_for_status()
	# Requests doesn't correctly guess this is utf-8
	html = BeautifulSoup(resp.content.decode(), "html.parser")
	posts = []
	for a in html.find_all("a", href=re.compile(r"^\?id=")):
		id = a["href"].removeprefix("?id=")
		posts.append((id, a.parent))
	return posts

def send_post(client, stream, topic, id, html):
	content = blog_to_md(id, html)
	client.request("POST", "messages",
		type="stream",
		to=stream,
		topic=topic,
		content=content,
	)

def save_post(save_dir, id, html):
	hash = b64encode(sha256(html).digest(), b"-_").decode().rstrip("=")
	filename = f"{id}-{hash}.json"
	filepath = os.path.join(save_dir, filename)
	if os.path.exists(filepath):
		return
	content = {
		"id": id,
		"hash": hash,
		"retrieved_at": datetime.utcnow().isoformat() + "Z",
		"html": html,
	}
	atomic_write(filepath, json.dumps(content) + "\n")

# This is copied from common, which isn't currently installed in zulip_bots.
# Fix that later.
def atomic_write(filepath, content):
	if isinstance(content, str):
		content = content.encode("utf-8")
	temp_path = "{}.{}.temp".format(filepath, uuid4())
	dir_path = os.path.dirname(filepath)
	os.makedirs(dir_path, exist_ok=True)
	with open(temp_path, 'wb') as f:
		f.write(content)
	try:
		os.rename(temp_path, filepath)
	except FileExistsError:
		os.remove(temp_path)

def main(config_file, interval=60, test=False, stream='bot-spam', topic='Blog Posts', save_dir=None):
	"""Post to zulip each new blog post, checking every INTERVAL seconds.
	Will not post any posts that already exist, unless --test is given
	in which case it will print the most recent on startup."""
	config = get_config(config_file)
	client = Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])
	seen = set()
	first = True
	while True:
		start = time.time()
		try:
			posts = get_posts()
		except Exception:
			logging.exception("Failed to get posts")
		else:
			if save_dir is not None:
				for id, html in posts:
					save_post(save_dir, id, str(html))
			if first:
				seen = set(id for id, html in posts)
				if test:
					id, html = posts[0]
					send_post(client, stream, topic, id, html)
				first = False
			else:
				for id, html in posts[::-1]:
					if id not in seen:
						send_post(client, stream, topic, id, html)
						seen.add(id)
		remaining = start + interval - time.time()
		if remaining > 0:
			time.sleep(remaining)


if __name__ == '__main__':
	argh.dispatch_command(main)
