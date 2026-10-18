FROM debian:13 AS build
# install python & pip, and tell python we're fine with messing with the system env
# install wget so we can download a deno binary (deno is not packaged for debian)
# install unzip so we can unpack deno
RUN apt update && apt install -y --no-install-recommends python3 python3-pip unzip wget \
    && rm /usr/lib/python3.13/EXTERNALLY-MANAGED \
    && rm -rf /var/lib/apt/lists/*

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# fetch deno binary from github release
ENV DENO_VERSION=2.9.6
RUN wget https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip \
    && unzip deno-x86_64-unknown-linux-gnu.zip -d /usr/local/bin \
    && rm deno-x86_64-unknown-linux-gnu.zip

# Install actual application
COPY downloader /tmp/downloader
RUN pip install /tmp/downloader && rm -r /tmp/downloader

# Install yt-dlp last as it changes often
RUN pip install 'yt-dlp[default]'

FROM debian:13
# install python
RUN apt update && apt install -y python3 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local /usr/local
LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "downloader", "--base-dir", "/mnt"]
