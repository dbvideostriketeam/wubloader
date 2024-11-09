FROM alpine:3.20
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev postgresql-dev file make busybox-extras zlib-dev jpeg-dev && rm /usr/lib/python3.12/EXTERNALLY-MANAGED

# Try to get wheels working
RUN pip install --upgrade pip wheel

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent==22.10.2

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
RUN apk add postgresql-dev postgresql-client ffmpeg
COPY cutter /tmp/cutter
RUN pip install /tmp/cutter && rm -r /tmp/cutter

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "cutter", "--base-dir", "/mnt"]
