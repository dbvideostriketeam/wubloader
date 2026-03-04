FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
# install ffmpeg, libjpeg-dev, zlib1g-dev for doing OCR stuff
# install libpq-dev for postgres connectivity
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED
RUN apt update && apt install -y libpq-dev
RUN apt update && apt install -y ffmpeg libjpeg-dev zlib1g-dev

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Actual application
COPY bus_analyzer /tmp/bus_analyzer
RUN pip install /tmp/bus_analyzer && cp -r /tmp/bus_analyzer/prototypes / && rm -r /tmp/bus_analyzer

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "bus_analyzer"]
