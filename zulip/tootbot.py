
import argh
import yaml
from mastodon import Mastodon

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
		content = format_content(reblog["content"])
		return f"{sender} reblogged {boostee}'s [post]({boost_url})\n{content}"

	return f"{"


class Listener(Mastodon.StreamListener):
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
		self.send(self.post_topic, format_status(status))

	def on_delete(self, status_id):
		logging.info(f"Got delete: {status_id}")
		self.send(self.post_topic, f"*Status with id {status_id} was deleted*")

	def on_status_update(self, status):
		logging.info(f"Got status update: {status!r}")
		self.send(self.post_topic, f"*The following status has been updated*\n{format_status(status)}")

	def on_notification(self, notification):
		logging.info(f"Got {notification['type']} notification: {notification!r}")
		if notification["type"] != "mention":
			return
		self.send(self.notification_topic, format_status(status))


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
	mastodon = Mastodon(api_base_url=mc["url"], access_token=mc["access_token"])
	listener = Listener(zulip_client, stream, post_topic, notification_topic)

	logging.info("Starting")
	mastodon.stream_user(listener)


@cli
def get_access_token(conf_file):
	"""Do OAuth login flow and obtain an access token."""
	mc = get_config(conf_file)["mastodon"]
	mastodon = Mastodon(client_id=mc["client_id"], client_secret=mc["client_secret"], api_base_url=mc["url"])
	print("Go to the following URL to obtain an access token:")
	print(mastodon.auth_request_url(scopes=["read:notifications", "read:statuses"]))


if __name__ == '__main__':
	cli()
