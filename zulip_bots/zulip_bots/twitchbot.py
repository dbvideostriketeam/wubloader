
import gevent.monkey
gevent.monkey.patch_all()

import logging

import argh
import girc

from . import zulip
from .config import common_setup, get_config


def run(zulip_client, nick, oauth_token, stream, topic):
	chat_client = girc.Client(
		hostname="irc.chat.twitch.tv",
		port=6697,
		ssl=True,
		nick=nick,
		password=oauth_token,
		twitch=True,
	)

	@chat_client.handler() # handle all messages
	def log_message(chat_client, message):
		logging.info(f"Got message: {message}")

	@chat_client.handler(command="WHISPER")
	def handle_whisper(chat_client, message):
		display_name = message.tags["display-name"]
		user = message.sender
		logging.info(f"Got whisper from {display_name!r} (username {user!r})")
		zulip_client.send_to_stream(stream, topic, f"**{nick}** received a Twitch DM from [{display_name}](https://twitch.tv/{user})")

	chat_client.start()
	logging.info("Chat client connected")
	chat_client.wait_for_stop()
	logging.warning("Chat client disconnected")


def main(conf_file, stream="bot-spam", topic="Twitch DMs", retry_interval=10, metrics_port=8014):
	"""
	config, in json or yaml format:
		twitch_username
		twitch_token
		zulip_url
		zulip_email
		zulip_api_key
	"""
	common_setup(metrics_port)

	config = get_config(conf_file)

	zulip_client = zulip.Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])

	while True:
		try:
			run(zulip_client, config["twitch_username"], config["twitch_oauth_token"], stream, topic)
		except Exception:
			logging.exception("Chat client failed")

		# We might get here either from an error, or because client disconnected.
		# Either way, try to re-connect.
		logging.info(f"Retrying in {retry_interval} seconds")
		gevent.sleep(retry_interval)


if __name__ == '__main__':
	argh.dispatch_command(main)
