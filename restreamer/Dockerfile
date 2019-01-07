FROM alpine:3.7
# dependencies needed for compiling c extensions, plus ffmpeg for cutting
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py2-pip gcc python-dev musl-dev ffmpeg busybox-extras

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY restreamer /tmp/restreamer
RUN pip install /tmp/restreamer && rm -r /tmp/restreamer

ENTRYPOINT ["python2", "-m", "restreamer", "--base-dir", "/mnt"]
