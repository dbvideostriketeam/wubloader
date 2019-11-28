
import json

from common.googleapis import GoogleAPIClient

# Youtube video to look up (look at this graph)
YOUTUBE_VIDEO_ID = 'sIlNIVXpIns'

# Sheet id to look up (DB2019 public sheet)
SHEET_ID = '15t-UsfNlP5xUxLTLH-EUjrOYriOvXuNGAPxi_8EZJhU'


def youtube(client):
	client.request('GET', 'https://www.googleapis.com/youtube/v3/videos',
		params={'part': 'id', 'id': YOUTUBE_VIDEO_ID},
	).raise_for_status()


def sheets(client):
	client.request('GET',
		'https://sheets.googleapis.com/v4/spreadsheets/{}/values/A1'.format(SHEET_ID),
	).raise_for_status()


ACTIONS = {
	'youtube': youtube,
	'sheets': sheets,
}


def main(
	*targets
):
	"""Does an action on the given google api targets, preventing issues due to api inactivity.
	A target should consist of a comma-seperated list of apis to hit, then a colon, then a creds file.
	eg. "sheets,youtube:my_creds.json".
	"""
	for target in targets:
		if ':' not in target:
			raise ValueError("Bad target: {!r}".format(target))
		apis, credfile = target.split(':', 1)
		apis = apis.split(',')
		with open(credfile) as f:
			creds = json.load(f)
		client = GoogleAPIClient(creds['client_id'], creds['client_secret'], creds['refresh_token'])
		for api in apis:
			if api not in ACTIONS:
				raise ValueError("No such api {!r}".format(api))
			ACTIONS[api](client)
