FROM ubuntu:18.04
# dependencies needed for compiling c extensions
RUN chmod 1777 /tmp && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install --yes python-pip python-dev file gcc make ffmpeg

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY restreamer /tmp/restreamer
RUN pip install /tmp/restreamer && rm -r /tmp/restreamer

ENTRYPOINT ["python2", "-m", "restreamer", "--base-dir", "/mnt"]
