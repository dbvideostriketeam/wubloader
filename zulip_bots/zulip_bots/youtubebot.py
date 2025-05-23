
import gevent.monkey
gevent.monkey.patch_all()

import json
import logging
import time

from common.googleapis import GoogleAPIClient

from .config import get_config
from .zulip import Client

def get_comments(google, channel_id):
	resp = google.request("GET",
		"https://www.googleapis.com/youtube/v3/commentThreads",
		params={
			"part": "snippet",
			"allThreadsRelatedToChannelId": channel_id,
			"maxResults": "100",
			"textFormat": "plainText",
		}
	)
	resp.raise_for_status()
	items = resp.json()["items"][::-1] # flip direction so we get earliest first
	if items:
		earliest = items[0]["snippet"]["topLevelComment"]
		logging.info(f"Got {len(items)} comment threads, oldest is {earliest['id']} at {earliest['snippet']['publishedAt']}")
	else:
		logging.info("Got no comment threads")
	# We could look at replies, but since we can only check for new replies in the first 100 threads,
	# we'd rather just never show them than confuse people when they don't show up sometimes.
	comments = []
	for thread in items:
		logging.debug(f"Got thread: {json.dumps(thread)}")
		comment = thread["snippet"]["topLevelComment"]
		comment["videoId"] = thread["snippet"]["videoId"]
		comments.append(comment)
	return comments


def show_comment(zulip, stream, topic, comment):
	c = comment["snippet"]
	author = f"[{c['authorDisplayName']}]({c['authorChannelUrl']})"
	video = f"https://youtu.be/{comment['videoId']}"
	message = f"{author} commented on {video}:\n```quote\n{c['textDisplay']}\n```"
	logging.info(f"Sending message to {stream}/{topic}: {message!r}")
	# Empty stream acts as a dry-run mode
	if stream:
		zulip.send_to_stream(stream, topic, message)


def main(conf_file, interval=60, one_off=0, stream="bot-spam", topic="Youtube Comments", keep=1000, log="INFO"):
	"""Config:
		zulip_url
		zulip_email
		zulip_api_key
		channel_id
		google_credentials_file:
			Path to json file containing at least:
				client_id
				client_secret
				refresh_token
			These creds should be authed as the target account with Youtube Data API read perms

	In one-off=N mode, get the last N comments and show them, then exit.
	"""
	logging.basicConfig(level=log)

	config = get_config(conf_file)
	zulip = Client(config["zulip_url"], config["zulip_email"], config["zulip_api_key"])
	with open(config["google_credentials_file"]) as f:
		credentials = json.load(f)
	google = GoogleAPIClient(credentials["client_id"], credentials["client_secret"], credentials["refresh_token"])
	channel_id = config["channel_id"]

	if one_off:
		comments = get_comments(google, channel_id)
		for comment in comments[-one_off:]:
			show_comment(zulip, stream, topic, comment)
		return

	seen = None
	while True:
		start = time.monotonic()

		if seen is None:
			# Get latest messages as of startup, so we know what's new next time
			seen = [comment["id"] for comment in get_comments(google, channel_id)]
		else:
			for comment in get_comments(google, channel_id):
				if comment["id"] in seen:
					logging.debug(f"Comment {comment['id']} already seen, skipping")
					continue
				show_comment(zulip, stream, topic, comment)
				seen.append(comment["id"])
		seen = seen[-keep:]

		remaining = start + interval - time.monotonic()
		logging.debug(f"Keeping {len(seen)} seen, waiting {remaining:.2f}s")
		if remaining > 0:
			time.sleep(remaining)


if __name__ == '__main__':
	import argh
	argh.dispatch_command(main)
