

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
