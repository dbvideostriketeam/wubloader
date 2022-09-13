
import os
from io import BytesIO

from PIL import Image

# The region of the frame image to place on the template.
# Format is (top_left_x, top_left_y, bottom_right_x, bottom_right_y).
# The frame is scaled to the size of the template before this is done.
FRAME_CROP = None # no crop

# The location in the template to place the frame image after cropping.
# Format is (x, y) of top-left corner.
FRAME_LOCATION = (0, 90)


def compose_thumbnail_template(base_dir, template_name, frame_data):
	template_path = os.path.join(base_dir, "thumbnail_templates", f"{template_name}.png")
	template = Image.open(template_path)
	# PIL can't load an image from a byte string directly, we have to pretend to be a file
	frame = Image.open(BytesIO(frame_data))

	# The parameters of how we overlay the template are hard-coded for now.
	# We can make this configurable later if needed.

	# Create a new blank image of the same size as the template
	result = Image.new('RGBA', template.size)
	# If the frame is not the same size, scale it so it is.
	# For choice of rescaling filter, pick LANCZOS (aka. ANTIALIAS) as it is highest quality
	# and we don't really care about performance.
	if frame.size != template.size:
		frame = frame.resize(template.size, Image.LANCZOS)
	# Insert the frame at the desired location and cropping
	if FRAME_CROP is not None:
		frame = frame.crop(FRAME_CROP)
	result.paste(frame, FRAME_LOCATION)
	# Place the template "on top", letting the frame be seen only where the template's alpha
	# lets it through.
	result.alpha_composite(template)

	buf = BytesIO()
	# PIL can't save an image to a byte string directly, we have to pretend to write it to
	# a file, rewind the file, then read it again.
	result.save(buf, format='png')
	buf.seek(0)
	return buf.read()
