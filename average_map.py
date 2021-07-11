
import atexit
import tempfile
import os
import subprocess
from uuid import uuid4
from shutil import rmtree

import argh
from PIL import Image
import cv2
import numpy


@argh.arg('videos', nargs='*')
def main(output_file, videos, maxlen=900):
	image = Image.new('RGB', (maxlen, len(videos)))

	tempdir = tempfile.mkdtemp()
	atexit.register(lambda: rmtree(tempdir, ignore_errors=True))

	for row, video in enumerate(videos):
		print "Processing video {}: {}".format(row, video)
		rowdir = os.path.join(tempdir, str(uuid4()))
		os.mkdir(rowdir)
		subprocess.check_call([
			'ffmpeg', '-hide_banner',
			'-i', video,
			'-r', '2',
			os.path.join(rowdir, 'frame%08d.png'),
		])
		for i, frame in enumerate(sorted(os.listdir(rowdir))):
			print "Processing frame {}".format(frame)
			filepath = os.path.join(rowdir, frame)
			if i >= maxlen:
				break

			## resize to 1,1, mostly center pixel
			#color = Image.open(filepath).resize((1, 1)).convert('RGB').getpixel((0, 0))

			## avg without black, in python
			#frame_im = Image.open(filepath).convert('RGB')
			#avg_color = (0, 0, 0)
			#count = 0
			#for color in frame_im.getdata():
			#	if color != (0,0,0):
			#		avg_color = tuple(a + b for a, b in zip(avg_color, color))
			#		count += 1
			#if count > 0:
			#	avg_color = tuple(a / count for a in avg_color)
			#else:
			#	avg_color = (0, 0, 0)
			#image.putpixel((i, row), tuple(avg_color))

			## true avg using numpy
			#avg_per_row = numpy.average(cv2.imread(filepath), axis=0)
			#avg = numpy.average(avg_per_row, axis=0)
			#image.putpixel((i, row), tuple(map(int, avg)))

			## avg without black, numpy
			im = cv2.imread(filepath)
			non_black = im[im.sum(axis=2) != 0]
			avg = numpy.average(non_black, axis=0)
			try:
				# note numpy flips the RGB values to BGR for some reason, so flip back
				color = tuple(map(int, avg))[::-1]
			except ValueError: # avg is NaN because all pixels black
				color = (0, 0, 0)
			image.putpixel((i, row), color)


		rmtree(rowdir)

	image.save(output_file)


if __name__ == '__main__':
	argh.dispatch_command(main)
