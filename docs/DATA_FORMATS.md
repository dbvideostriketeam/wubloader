
A list of all the info we may potentially save, and what format it is in.

All filepaths are relative to the "base directory" used for storage.
A unix filesystem (case-sensitive, no special characters except `/`) is assumed.

When not otherwise specified, a "hash" of content is a sha256 hash encoded to url-safe base64 without padding.
For example, the empty string hashes to `47DEQpj8HBSa_-TImW_5JCeuQeRkm5NMpJWZG3hSuFU`

## Video segments

Stream video data is saved in MPEG-TS segments, with filepaths:
`CHANNEL/QUALITY/HOUR/TIME-DURATION-TYPE-HASH.ts`
Where:
- HOUR is `%Y-%m-%DT%H`
- TIME is `%M-%S`
- DURATION is a non-negative float value
- TYPE is one of:
    - `full` - A normal segment
	- `suspect` - A segment which we suspect to not be fully correct
	- `partial` - A segment which we know to be incomplete

It is assumed that any set of segments can be concatenated to produce a playable video
(once timestamps have been corrected).

## Chat logs

Chat logs are saved in "batch" files with filepaths:
`CHANNEL/chat/HOUR/TIME-HASH.json`
Where HOUR and TIME are as per segment files.

Each batch file is newline-delimited json containing chat log entries.
Each entry corresponds to an IRC PRIVMSG or other command like a JOIN, CLEARCHAT or ROOMSTATE.
An entry has a `time` and a `time_range` field, with the estimated "true" time of the message
being within the range `[time, time + time_range]`.
The `receivers` field contains each unique chat archiver instance that observed this message,
and the timestamp at which they recieved it. This information is primarily for debugging purposes.

Batches from multiple machines will be merged periodically,
so while it may be possible to observe two batches for the same time, this should be temporary.
Messages may be present in both batches.

## Blog posts

Website blog posts are captured by blogbot with filepaths:
`blogs/ID-HASH.json`
Multiple files with the same ID represent edits of the same blog post.
Each JSON file contains an object with the html content plus some other metadata.

## Coverage maps

`segment-coverage` generates coverage map images with filepath:
`coverage-maps/CHANNEL_QUALITY_coverage.png`
along with a html file of the same name which shows the image with a periodic refresh.

The image files show one pixel per 2 seconds, with the color depending on the coverage state at that time.
See `segment-coverage` for more detail.

## Emotes

Emote data is saved by chat-archiver for each unique emote seen in chat, with filepath:
`emotes/ID/{light,dark}-{1.0,2.0,3.0}`
These 6 files per emote represent all the variants of the emote image that twitch provides.

Each file is either a PNG or a GIF - consult file magic values (the first 4 bytes) to determine which.

## Downloaded media

Several components will download arbitary media when they see a URL:
- in a blog or social media post
- in the media links column of the sheet
- in chat

Because these links are potentially untrusted, we exercise a high degree of caution in fetching them.
See `common/common/media.py` for details.

These files are saved in:
`media/URLHASH/FILEHASH.EXT`
Where URLHASH and FILEHASH are hashed in the normal way, but of the request URL and response content respectively.
EXT is guessed based on the content-type and may not be correct.

Note the URL hash will include any query string, etc.
A file may be retrieved multiple times, if this results in different content then multiple files will be present
under the same URL hash.

## Pubnub data

`pubbot` watches known PubNub streams and saves an event log `pubnub-log.json`.
This is a newline-delimited json file containing messages which can be distingished by the `type` field:
- `startup`: Records that pubbot just started. May be used to imply there may have been missed messages preceeding it.
- `total`: An update to the donation total
- `prize`: An update to the highest bid on a prize
- `unknown`: An unrecognized pubnub message
- `error`: Something went wrong while handling the message

The details of what is contained in each type depend on pubnub - you should read the pubbot code.

## Twitch stats

`twitch_stats` bot watches the twitch Hermes event stream via a websocket.
This is a reverse-engineered API from the twitch website.

It saves an event log `twitch_stats.json`. This is a newline-delimited json file containing messages
with the fields:
- `topic`: The name of the topic associated with the message
- `channel_id`: The twitch user id associated with the message
- `received_at`: Unix timestamp of when the message was seen
- `message`: The payload, which depends on topic.

We are subscribed to info on viewer counts, polls and predictions.
Known formats:
- When `topic == "video-playback-by-id"`, the `message.viewers` field contains the stream viewer count and the `message.server_time` field contains the server time this observation was made at.
  The server time should be considered more accurate than our recieve time.

## Mastodon toots

`tootbot` watches the Desert Bus and VST mastodon accounts for updates.
It writes these update events to `tootbot.json`. The content of these depends on the mastodon API,
see `tootbot` for details.

## Prize info

`prizebot` watches the desertbus.org website and periodically scrapes prize data.
It writes scraped data once per minute to `prizes.json`.
This is a newline-delimited json file containing entries with keys:
- `time`: the unix timestamp of the scrape
- `live`: list of live auction prizes
- `silent`: list of silent auction prizes
- `giveaway`: list of giveaway prizes

Where each prize list item has the keys:
- `id`: website id of prize, NOT the same as the internal prize id that crafters work with
- `link`: URL of the prize's page on the website
- `type`: `live`, `silent` or `giveaway`
- `title`: The name of the prize
- `state`: One of:
	- `pending`: Not started yet
	- `active`: Currently open or waiting to draw
	- `sold`: A winner has been announced
- `result`: Free-form text taken from the website describing the outcome if state == `sold`, eg. `Won by NoDonorAccount`
