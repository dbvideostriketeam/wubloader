
import json
import logging
import time

import argh
import requests
import bs4
from bs4 import BeautifulSoup

logging.basicConfig(level='INFO')

class Client(object):
	def __init__(self, base_url, email, api_key):
		self.base_url = base_url
		self.email = email
		self.api_key = api_key

	def request(self, method, *path, **params):
		if method == 'GET':
			args = {"params": params}
		else:
			args = {"data": {
				k: v if isinstance(v, str) else json.dumps(v)
				for k, v in params.items()
			}}
		url = "/".join([self.base_url, "api/v1"] + list(map(str, path)))
		resp = requests.request(method, url, auth=(self.email, self.api_key), **args)
		if not resp.ok:
			logging.info(repr(params))
			logging.info(f"Got {resp.status_code} for {url}: {resp.text}")
		resp.raise_for_status()
		return resp.json()

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

def blog_to_md(blog):
	md_content = html_to_md(BeautifulSoup(blog["content"], "html.parser"))
	return "\n".join([
		"Blog Post: [{title}](https://desertbus.org/?id={id})".format(**blog),
		"Posted by {author} at <time:{date}>".format(**blog),
		"```quote",
		md_content,
		"```",
	])

def get_posts():
	"""Get all blog posts on the front page"""
	resp = requests.get("https://desertbus.org/wapi/blog/1")
	resp.raise_for_status()
	posts = resp.json()["posts"]
	logging.info("Fetched posts: {}".format(", ".join(post['id'] for post in posts)))
	return posts

def send_post(client, stream, topic, post):
	content = blog_to_md(post)
	client.request("POST", "messages",
		type="stream",
		to=stream,
		topic=topic,
		content=content,
	)

def main(zulip_url, zulip_email, zulip_key, interval=60, test=False, stream='bot-spam', topic='Blog Posts'):
	"""Post to zulip each new blog post, checking every INTERVAL seconds.
	Will not post any posts that already exist, unless --test is given
	in which case it will print the most recent on startup."""
	client = Client(zulip_url, zulip_email, zulip_key)
	seen = set()
	first = True
	while True:
		start = time.time()
		try:
			posts = get_posts()
		except Exception:
			logging.exception("Failed to get posts")
		else:
			if first:
				seen = set(post['id'] for post in posts)
				if test:
					send_post(client, stream, topic, posts[0])
				first = False
			else:
				for post in posts[::-1]:
					if post['id'] not in seen:
						send_post(client, stream, topic, post)
						seen.add(post['id'])
		remaining = start + interval - time.time()
		if remaining > 0:
			time.sleep(remaining)


if __name__ == '__main__':
	argh.dispatch_command(main)
