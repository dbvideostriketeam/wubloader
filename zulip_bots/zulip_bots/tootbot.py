

import argh
import logging
import time

import mastodon
import yaml
from bs4 import BeautifulSoup

import zulip

cli = argh.EntryPoint()


def get_config(conf_file):
	with open(conf_file) as f:
		return yaml.safe_load(f)


def format_account(account):
	return f"**[{account['display_name']}]({account['url']})**"


def format_status(status):
	sender = format_account(status["account"])
	url = status["url"]
	visibility = status["visibility"]
	reply = status["in_reply_to_id"]
	reblog = status["reblog"]

	# private messages should not show content.
	if visibility not in ("public", "unlisted"):
		kind = "message"
		if reblog is not None:
			kind = "boost"
		if reply is not None:
			kind = "reply"
		return f"{sender} sent [a {visibility} {kind}]({url})"

	if reblog is not None:
		boostee = format_account(reblog["account"])
		boost_url = reblog["url"]
		content = format_content(reblog)
		return f"{sender} reblogged {boostee}'s [post]({boost_url})\n{content}"

	content = format_content(status)

	if reply:
		return f"{sender} [replied]({url}) to message {reply}:\n{content}"

	return f"{sender} [posted]({url}):\n{content}"


def md_wrap(kind, inner):
	"""
		Wrap inner in a markdown block with given kind, eg. "quote" or "spoiler TEXT HERE"
	"""
	return "\n".join([
		f"```{kind}",
		inner,
		"```",
	])


def format_content(status):
	# Main status text should be rendered into text and quoted
	html = BeautifulSoup(status["content"], "html.parser")
	text = html_to_md(html)
	parts = [md_wrap("quote", text)]
	# Append attachments, with the link name being the alt text.
	# For images at least, zulip will auto-preview them.
	for attachment in status["media_attachments"]:
		type = attachment["type"]
		description = attachment["description"] or "(no description provided)"
		url = attachment["url"]
		parts.append(f"Attached {type}: [{description}]({url})")
	output = "\n".join(parts)
	# If content warnings present, wrap in a spoiler block.
	warning = status["spoiler_text"]
	if warning:
		output = md_wrap(f"spoiler {warning}", output)
	return output


def html_to_md(html):
	"""
	Take a status HTML as a BeautifulSoup object
	and make a best-effort attempt to render it in markdown:
	* Convert each <p> section to text ending in a newline
	* Convert <a> tags to links
	* Convert formatting tags to the markdown equivalent
	* Ignore other tags and just pass through their inner content

	Note that zulip has no way of escaping markdown syntax, so if a message contains
	characters that happen to be valid markdown, there's not much we can do about it.
	The only thing that could cause problems is a malicious input that breaks out of
	our surrounding quote block. And you know what? Fine, they can have that. We can always
	just read the link to see the real deal.
	"""
	if html.name is None:
		# Raw string, return as-is.
		return html

	if html.name == "br":
		# <br> should never have any contents, and just become a newline
		return "\n"

	# Lists need to be handled specially as they should only contain <li> elements
	# and the <li> elements should be rendered differently depending on the outer element.
	if html.name in ("ul", "ol"):
		prefix = {"ul": "*", "ol": "1."}[html.name]
		items = []
		for item in html.children:
			if item.name != "li":
				logging.warning(f"Ignoring non-<li> inside <{html.name}> element")
				continue
			inner = "".join(html_to_md(child) for child in item.children)
			# Prepend two spaces to every line, to create a "nesting" effect
			# for sub-lists. This may break things if mixed with blockquotes but oh well.
			inner = "\n".join("  " + line for line in inner.split("\n"))
			items.append(prefix + inner)
		return "\n".join(items)

	# Get contents recursively. Bail if empty as this might cause weird things if rendered naively,
	# eg. <i></i> would be rendered ** which would actually make other text bold.
	inner = "".join(html_to_md(child) for child in html.children)
	if not inner:
		return ""

	# <p> should insert a newline at the end
	if html.name == "p":
		return f"{inner}\n"

	# <a> should become a link
	href = html.get("href")
	if html.name == "a" and href:
		return f"[{inner}]({href})"

	# <blockquote> creates a nested quote block which is its own paragraph.
	if html.name == "blockquote":
		return md_wrap("quote", inner)

	# The following tag types are simple character-based format wrappers.
	# Note we don't handle <u> due to lack of underline formatting in markdown.
	# We treat all headings as bold.
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

	# For any other types, most notably <span> but also anything that we don't recognize,
	# just pass the inner text though unchanged.
	return inner


LINE = "\n---"


class Listener(mastodon.StreamListener):
	def __init__(self, zulip_client, stream, post_topic, notification_topic):
		self.zulip_client = zulip_client
		self.stream = stream
		self.post_topic = post_topic
		self.notification_topic = notification_topic

	def send(self, topic, content):
		logging.info(f"Sending message to {self.stream}/{topic}: {content!r}")
		self.zulip_client.send_to_stream(self.stream, topic, content)

	def on_update(self, status):
		logging.info(f"Got update: {status!r}")
		self.send(self.post_topic, format_status(status) + LINE)

	def on_delete(self, status_id):
		logging.info(f"Got delete: {status_id}")
		self.send(self.post_topic, f"*Status with id {status_id} was deleted*")

	def on_status_update(self, status):
		logging.info(f"Got status update: {status!r}")
		self.send(self.post_topic, f"*The following status has been updated*\n{format_status(status)}" + LINE)

	def on_notification(self, notification):
		logging.info(f"Got {notification['type']} notification: {notification!r}")
		if notification["type"] != "mention":
			return
		self.send(self.notification_topic, format_status(notification["status"]) + LINE)


@cli
def main(conf_file, stream="bot-spam", post_topic="Toots from Desert Bus", notification_topic="Mastodon Notifications"):
	"""
	Run the actual bot.

	Config, in json or yaml format:
		zulip:
			url
			email
			api_key
		mastodon:
			url
			client_id # only required for get-access-token
			client_secret # only required for get-access-token
			access_token # only required for main
	"""
	logging.basicConfig(level='INFO')

	conf = get_config(conf_file)
	zc = conf["zulip"]
	mc = conf["mastodon"]

	zulip_client = zulip.Client(zc["url"], zc["email"], zc["api_key"])
	mastodon_client = mastodon.Mastodon(api_base_url=mc["url"], access_token=mc["access_token"])
	listener = Listener(zulip_client, stream, post_topic, notification_topic)

	RETRY_INTERVAL = 1

	while True:
		logging.info("Starting")
		try:
			mastodon_client.stream_user(listener)
		except mastodon.MastodonNetworkError:
			logging.warning(f"Lost connection, reconnecting in {RETRY_INTERVAL}s")
			time.sleep(RETRY_INTERVAL)


@cli
def get_access_token(conf_file):
	"""Do OAuth login flow and obtain an access token."""
	mc = get_config(conf_file)["mastodon"]
	client = mastodon.Mastodon(client_id=mc["client_id"], client_secret=mc["client_secret"], api_base_url=mc["url"])
	print("Go to the following URL to obtain an access token:")
	print(client.auth_request_url(scopes=["read:notifications", "read:statuses"]))


if __name__ == '__main__':
	cli()
