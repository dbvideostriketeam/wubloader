FROM alpine:3.14
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev file make busybox-extras

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install girc, it's not really properly published on pypi so we pull it in via submodule
COPY chat_archiver/girc /tmp/girc
RUN pip install /tmp/girc && rm -r /tmp/girc

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Actual application
COPY chat_archiver /tmp/archiver
RUN pip install /tmp/archiver && rm -r /tmp/archiver

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "chat_archiver", "--base-dir", "/mnt"]
