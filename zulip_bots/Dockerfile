FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

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
