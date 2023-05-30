

import struct

class FixTS():
	"""Does stream processing on an MPEG-TS stream, adjusting all timestamps in it.
	The stream will be adjusted such that the first packet starts at the given start_time,
	with all other packets adjusted to be the same time relative to that packet.
	In other words, a video that goes from 01:23:45 to 01:24:45 will be retimed to instead
	go from (for example) 00:10:00 to 00:11:00.

	The object maintains an internal buffer of data.
	Use feed() to add more data. Data will be removed from the buffer when a whole packet
	can be parsed, and any completed data will be returned from feed().
	Finally, when there is no more data, call end() to assert there is no left-over data
	and provide the final video end time.

	All timestamps are in seconds as a float.

	Example use:
		fixer = FixTimestamps(0)
		for chunk in input:
			fixed_data = fixer.feed(chunk)
			output(fixed_data)
		end_time = fixer.end()
	"""
	PACKET_SIZE = 188

	# We need to pad the end time to the time of the NEXT expected frame, or else
	# we'll overlap the last frame here with the first frame of the next segment.
	# We don't know what the correct frame rate should be and trying to determine
	# it from the PCR times might go wrong if the video data is weird or corrupt
	# (eg. dropped frames). Instead, we'll just assume it's 30fps and add 33ms.
	# This should be right the majority of the time, the results will still be mostly
	# fine even if it's meant to be 60fps, and above all it's consistent and predictable.
	NOMINAL_PCR_INTERVAL = 0.033

	def __init__(self, start_time):
		self.start_time = start_time
		# By definition, the first PCR timestamp will be set to start_time.
		# So this is always a safe "latest" value to start at, and it means that if
		# the video is ended with no PCR frames, we default to "same as start time".
		self.end_time = start_time
		# once starting PCR/PTS is known, contains value to add to each timestamp
		self.offsets = {"pcr": None, "pts": None}
		# buffers fed data until a whole packet can be parsed
		self.data = b""

	def feed(self, data):
		"""Takes more data as a bytestring to add to buffer.
		Fixes any whole packets in the buffer and returns them as a single bytestring."""
		self.data += data
		output = []
		while len(self.data) >= self.PACKET_SIZE:
			packet = self.data[:self.PACKET_SIZE]
			self.data = self.data[self.PACKET_SIZE:]
			fixed_packet = self._fix_packet(packet)
			output.append(fixed_packet)
		return b''.join(output)

	def end(self):
		"""Should be called when no more data will be added.
		Checks no data was left over, and returns the final end time (ie. start time + video duration).
		"""
		if len(self.data) > 0:
			raise ValueError("Stream has a partial packet remaining: {!r}", self.data)
		return self.end_time


	# PCRs (which represent the "time when encoded") can vary greatly between
	# encoded videos, sometimes with large offsets between the PCR and the PTS.
	# For example, a video might actually start at t=1, when the PCR starts at t=0.
	# During playback of such a video, the player would start at t=1. We want to effectively do the same,
	# and have the first actual content of the video start at the user's requested time.
	# So we want both the first PCR and the first PTS to be equal to start_time,
	# with no difference between them. The easiest way to do this is to track their offsets independently.
	def _convert_time(self, old_time, kind):
		# If this is the first one we've seen, use it to calibrate offset.
		if self.offsets[kind] is None:
			self.offsets[kind] = self.start_time - old_time
		new_time = old_time + self.offsets[kind]
		# It's possible that the second packet might have a PTS slightly earlier than the first
		# (eg. one is audio and one is video, and their start times slightly differ). We clamp
		# the value so that it never goes earlier than the user's requested start time. This may
		# cause some minor artifacting on the first packet of a stream, but saves us from invalid
		# packets which cause further issues.
		new_time = max(self.start_time, new_time)
		# Keep track of the nominal "end time" based on latest PCR or PTS time.
		# This can be thought of as finding the "video length" as max(latest ts - first ts) for any kind.
		# then adding the requested start time to it to get the end time.
		new_end = new_time + self.NOMINAL_PCR_INTERVAL
		self.end_time = max(self.end_time, new_end)
		return new_time

	def _fix_packet(self, packet):
		""" 
		- If an adaptation field is present and contains a PCR, fix the PCR
		- If packet is the start of a unit, and the unit begins with 0x0001
		  (ie. it's an elementary stream and not a table):
			- If the packet header contains a PTS, fix the PTS
			- If the packet header cannot be decoded far enough (not enough data in first packet),
			  bail - we don't care about this edge case.
		"""
		assert len(packet) == self.PACKET_SIZE 

		def check(expr, reason):
			if not expr:
				raise ValueError("Packet cannot be parsed: {}\n{!r}".format(reason, packet))

		# Note this is a very simple, hacky parser that only parses as much as we need.
		# Useful links: https://en.wikipedia.org/wiki/MPEG_transport_stream

		# 4 byte header: "G" | TEI(1) PUSI(1) PRI(1) PID(5) | PID(8) | TSC(2) AFC(2) CONT(4)
		# Of interest to us:
		#   TEI: If set, data is known to be corrupt
		#   PUSI: If set, this packet contains a new payload unit
		#       This matters because payload unit headers contain a timestamp we need to edit
		#   TSC: If non-zero, indicates data is scrambled (we don't implement handling that)
		#   AFC: First bit indicates an adaptation field header is present, second bit indicates a payload
		check(packet[0:1] == b"G", "Sync byte is incorrect")
		check(packet[1] & 0x80 == 0, "Transport error indicator is set")
		pusi = bool(packet[1] & 0x40)
		check(packet[3] & 0xc0 == 0, "TSC indicates data is scrambled")
		has_adaptation_field = bool(packet[3] & 0x20)
		has_payload = bool(packet[3] & 0x10)

		if has_adaptation_field:
			field_length = packet[4]
			payload_index = 5 + field_length
			# According to the spec, the adaptation field header is at least 1 byte.
			# But in the wild we see a header as "present" except 0 bytes long.
			# We should just treat this as "not present"
			if field_length > 0:
				# The adaptation field is a bit field of 8 flags indicating whether optional
				# sections are present. Thankfully, the only one we're interested in (the PCR)
				# is always the first field if present, so we don't even need to check the others.
				has_pcr = bool(packet[5] & 0x10)
				if has_pcr:
					check(field_length >= 7, "Adaptation field indicates PCR but is too small")
					old_time = decode_pcr(packet[6:12])
					new_time = self._convert_time(old_time, 'pcr')
					encoded = encode_pcr(new_time)
					packet = packet[:6] + encoded + packet[12:]
					assert len(packet) == 188
		else:
			# No adapatation field, payload starts immediately after the packet header
			payload_index = 4

		if pusi:
			# Payload Unit Start Indicator indicates there is a new payload unit in this packet.
			# When set, there is an extra byte before the payload indicating where within the
			# payload the new payload unit starts.
			# A payload unit is a thing like a video frame, audio packet, etc. The payload unit header
			# contains a timestamp we need to edit.
			check(has_payload, "PUSI set but no payload is present")
			payload_pointer = packet[payload_index]
			# move index past payload pointer, then seek into payload to find start of payload unit.
			unit_index = payload_index + 1 + payload_pointer
			# The header we're after is only present in elementary streams, not in program tables.
			# We can tell the difference because streams start with a 0x0001 prefix,
			# whereas program tables start with a header where at least bits 0x0030 must be set.
			# Note wikipedia in https://en.wikipedia.org/wiki/Packetized_elementary_stream
			# claims the prefix is 0x000001, but that is including the payload pointer, which seems
			# to always be set to 0 for an elementary stream
			# (compare https://en.wikipedia.org/wiki/Program-specific_information which also includes
			# the payload pointer but says it can be any 8-bit value).
			if packet[unit_index : unit_index + 2] == b"\x00\x01":
				# unit header looks like: 00, 01, stream id, length(2 bytes), then PES header
				# The only thing we care about in the PES header is the top two bits of the second byte,
				# which indicates if timestamps are present.
				# It's possible that we didn't get enough of the payload in this one packet
				# to read the whole header, but exceedingly unlikely.
				check(unit_index + 6 < self.PACKET_SIZE, "Payload too small to read unit header")
				flags = packet[unit_index + 6]
				has_pts = bool(flags & 0x80)
				has_dts = bool(flags & 0x40)
				check(not has_dts, "DTS timestamp is present, we cannot fix DTS as it may cause packets to be before start_time")
				# Once again, PTS is the first optional field, so we don't need to worry
				# about other fields being present.
				if has_pts:
					pts_index = unit_index + 8
					check(pts_index + 5 <= self.PACKET_SIZE, "Payload too small to read PTS")
					raw = packet[pts_index : pts_index + 5]
					pts = decode_ts(raw, 2)
					pts = self._convert_time(pts, 'pts')
					encoded = encode_ts(pts, 2)
					packet = packet[:pts_index] + encoded + packet[pts_index + 5:]
					assert len(packet) == 188

		return packet


def bits(value, start, end):
	"""Extract bits [START, END) from value, where 0 is LSB"""
	size = end - start
	return (value >> start) & ((1 << size) - 1)


def decode_padded(value, spec):
	size = struct.calcsize(spec)
	pad = size - len(value)
	assert pad >= 0
	value = b"\0" * pad + value
	return struct.unpack(spec, value)[0]


def encode_pcr(seconds):
	assert seconds >= 0
	raw = int(seconds * 27000000)
	base, ext = divmod(raw, 300)
	assert base < 2**33
	value = (base << 15) + ext
	value = struct.pack('!Q', value)
	return value[2:]


def decode_pcr(value):
	value = decode_padded(value, '!Q')
	base = bits(value, 15, 48)
	extension = bits(value, 0, 9)
	raw = 300 * base + extension
	seconds = float(raw) / 27000000
	return seconds


def encode_ts(seconds, tag):
	# bits: TTTTxxx1 xxxxxxxx xxxxxxx1 xxxxxxxx xxxxxxx1
	# T is tag, x is bits of actual number
	assert seconds >= 0
	raw = int(seconds * 90000)
	a = bits(raw, 30, 33)
	b = bits(raw, 15, 30)
	c = bits(raw, 0, 15)
	value = 1 + (1 << 16) + (1 << 32) + (tag << 36) + (a << 33) + (b << 17) + (c << 1)
	value = struct.pack('!Q', value)
	return value[3:]


def decode_ts(value, tag):
	# bits: TTTTxxx1 xxxxxxxx xxxxxxx1 xxxxxxxx xxxxxxx1
	# T is tag, x is bits of actual number
	value = decode_padded(value, '!Q')
	assert bits(value, 36, 40) == tag 
	assert all(value & (1 << bit) for bit in [0, 16, 32])
	a = bits(value, 33, 36) 
	b = bits(value, 17, 32) 
	c = bits(value, 1, 16) 
	value = (a << 30) + (b << 15) + c 
	seconds = float(value) / 90000
	return seconds


if __name__ == '__main__':
	# simple test: read file from stdin, set start to first arg, output to stdout.
	import sys
	start_time = float(sys.argv[1])
	fixer = FixTS(start_time)
	chunk = None
	while chunk != b"":
		chunk = sys.stdin.buffer.read(8192)
		if chunk:
			output = fixer.feed(chunk)
			while output:
				written = sys.stdout.buffer.write(output)
				output = output[written:]
	end_time = fixer.end()
	sys.stderr.write(str(end_time) + '\n')
