import datetime
import os
import urllib
from collections import Counter


def generate_master(playlists):
	"""Generate master playlist. Playlists arg should be a map {name: url}.
	Little validation or encoding is done - please try to keep the names valid
	without escaping.
	"""
	lines = ["#EXTM3U"]
	for name, url in playlists.items():
		lines += [
			# We name each variant with a VIDEO rendition with no url
			'#EXT-X-MEDIA:TYPE=VIDEO,GROUP-ID="{name}",NAME="{name}",AUTOSELECT=YES,DEFAULT=YES'.format(name=name),
			'#EXT-X-STREAM-INF:VIDEO="{name}"'.format(name=name),
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
	for segment in segments:
		# TODO handle missing bits, stream endings, other stuff
		if segment is not None:
			path = '/'.join(segment.path.split('/')[-2:])
			lines.append("#EXTINF:{:.3f},live".format(segment.duration.total_seconds()))
			lines.append(urllib.quote(os.path.join(base_url, path)))
	return "\n".join(lines) + '\n'
