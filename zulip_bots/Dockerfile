FROM alpine:3.20
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev file make busybox-extras && rm /usr/lib/python3.12/EXTERNALLY-MANAGED

# Try to get wheels working
RUN pip install --upgrade pip wheel

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent==22.10.2

# Install girc, it's not really properly published on pypi so we pull it in via submodule.
# Also we should probably move the submodule out of chat_archiver now that it's used
# in multiple places.
COPY chat_archiver/girc /tmp/girc
RUN pip install /tmp/girc && rm -r /tmp/girc

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Actual application
COPY zulip_bots /tmp/zulip_bots
RUN pip install /tmp/zulip_bots && rm -r /tmp/zulip_bots

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "zulip_bots"]
