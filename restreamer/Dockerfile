FROM alpine:3.14
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev file make busybox-extras

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
RUN apk add ffmpeg
COPY restreamer /tmp/restreamer
RUN pip install /tmp/restreamer && rm -r /tmp/restreamer

ENTRYPOINT ["python3", "-m", "restreamer", "--base-dir", "/mnt"]
