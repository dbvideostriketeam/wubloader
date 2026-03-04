FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
# install libpq-dev for postgres connectivity
RUN apt update && apt install -y libpq-dev python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY backfiller /tmp/backfiller
RUN pip install /tmp/backfiller && rm -r /tmp/backfiller

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "backfiller", "--base-dir", "/mnt"]
