"""Hand-rolled multi-part HTTP body generator, because all the standard libraries are awful"""

import uuid

def multipart(parts, subtype="mixed"):
    """
	Make a multipart http body from a list of parts (content type, bytes).
	Returns (content type header, body)
    """
	# unique boundary string
    boundary = f"boundary-{uuid.uuid4()}"
    content_type = f'multipart/{subtype}; boundary="{boundary}"'
    
    chunks = [
		# for each part: boundary, headers, blank line, content
		b"\r\n".join([
			f"--{boundary}".encode(),
			f"Content-Type: {mime_type}".encode(),
			b"",
			content,
		]) for mime_type, content in parts
	]
	# final boundary
    chunks.append(f"--{boundary}--".encode())
    
    return content_type, b"\r\n".join(chunks) + b"\r\n"
