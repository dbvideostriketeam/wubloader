FROM debian:13 AS build
# install python & pip, and tell python we're fine with messing with the system env
# install ffmpeg, libjpeg-dev, zlib1g-dev for doing OCR stuff
# install libpq-dev for postgres connectivity
RUN apt update && apt install -y python3 python3-pip libpq-dev ffmpeg libjpeg-dev zlib1g-dev \
    && rm /usr/lib/python3.13/EXTERNALLY-MANAGED \
    && rm -rf /var/lib/apt/lists/*

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Actual application
COPY bus_analyzer /tmp/bus_analyzer
RUN pip install /tmp/bus_analyzer && cp -r /tmp/bus_analyzer/prototypes / && rm -r /tmp/bus_analyzer

FROM debian:13
RUN apt update && apt install -y --no-install-recommends python3 ca-certificates libpq5 ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local /usr/local
COPY --from=build /prototypes /prototypes
LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "bus_analyzer"]
