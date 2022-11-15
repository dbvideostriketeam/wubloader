import datetime
import os
import urllib.parse
from collections import Counter


def generate_master(playlists):
	"""Generate master playlist. Playlists arg should be a map {name: url}.
	Little validation or encoding is done - please try to keep the names valid
	without escaping.
	"""
	# Canned bandwidth estimates based on the quality name,
	# these may be entirely wrong but should be good enough.
	# "source" and other unlisted names map to 1080p.
	BANDWIDTHS = {
		"1080p": 6846146,
		"720p": 2373000,
		"480p": 1427999,
		"360p": 630000,
		"160p": 230000,
	}

	lines = ["#EXTM3U"]
	for name, url in playlists.items():
		bandwidth = BANDWIDTHS.get(name, BANDWIDTHS["1080p"])
		lines += [
			# We name each variant with a VIDEO rendition with no url
			'#EXT-X-MEDIA:TYPE=VIDEO,GROUP-ID="{name}",NAME="{name}",AUTOSELECT=YES,DEFAULT=YES'.format(name=name),
			'#EXT-X-STREAM-INF:VIDEO="{name}",NAME="{name}",BANDWIDTH={bandwidth}'.format(name=name, bandwidth=bandwidth),
			url,
		]
	return "\n".join(lines) + '\n'


def generate_media(segments, base_url):
	"""Generate a media playlist from a list of segments as returned by common.get_best_segments().
	Segments are specified as hour/name.ts relative to base_url.
	"""

	# We have to pick a "target duration". in most circumstances almost all segments
	# will be of that duration, so we get the most common duration out of all the segments
	# and use that.
	# If we have no segments, default to 6 seconds.
	non_none_segments = [segment for segment in segments if segment is not None]
	if non_none_segments:
		# Note most_common returns [(value, count)] so we unpack.
		((target_duration, _),) = Counter(segment.duration for segment in non_none_segments).most_common(1)
	else:
		target_duration = datetime.timedelta(seconds=6)

	lines = [
		"#EXTM3U",
		"#EXT-X-TARGETDURATION:{:.3f}".format(target_duration.total_seconds()),
	]

	# Note and remove any trailing None from the segment list - this indicates there is a hole
	# at the end, which means we should mark the stream as incomplete but not include a discontinuity.
	if segments and segments[-1] is None:
		incomplete = True
		segments = segments[:-1]
	else:
		incomplete = False

	# Remove any leading None from the segment list - this indicates there is a hole at the start,
	# which isn't actually meaningful in any way to us.
	# Note that in the case of segments = [None], we already removed it when we removed the trailing
	# None, and segments is now []. This is fine.
	if segments and segments[0] is None:
		segments = segments[1:]

	for segment in segments:
		if segment is None:
			# Discontinuity. Adding this tag tells the client that we've missed something
			# and it should start decoding fresh on the next segment. This is required when
			# someone stops/starts a stream and a good idea if we're missing a segment in a
			# continuous stream.
			lines.append("#EXT-X-DISCONTINUITY")
		else:
			# Each segment has two prefixes: timestamp and duration.
			# This tells the client exactly what time the segment represents, which is important
			# for the editor since it needs to describe cut points in these times.
			path = '/'.join(segment.path.split('/')[-2:])
			lines.append("#EXT-X-PROGRAM-DATE-TIME:{}".format(segment.start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")))
			lines.append("#EXTINF:{:.3f},live".format(segment.duration.total_seconds()))
			lines.append(urllib.parse.quote(os.path.join(base_url, path)))

	# If stream is complete, add an ENDLIST marker to show this.
	if not incomplete:
		lines.append("#EXT-X-ENDLIST")

	return "\n".join(lines) + '\n'
