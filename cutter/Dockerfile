FROM alpine:3.7
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py2-pip gcc python-dev musl-dev busybox-extras

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
RUN apk add postgresql-dev postgresql-client ffmpeg
COPY cutter /tmp/cutter
RUN pip install /tmp/cutter && rm -r /tmp/cutter

ENTRYPOINT ["python2", "-m", "cutter", "--base-dir", "/mnt"]
