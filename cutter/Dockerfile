FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
# install libpq-dev for postgres connectivity
# install ffmpeg for video cuts
# install libjpeg and zlib for thumbnail work
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED
RUN apt update && apt install -y libpq-dev
RUN apt update && apt install -y ffmpeg libjpeg-dev zlib1g-dev

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY cutter /tmp/cutter
RUN pip install /tmp/cutter && rm -r /tmp/cutter

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "cutter", "--base-dir", "/mnt"]
