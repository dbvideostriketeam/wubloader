FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
# install wget so we can download a deno binary (deno is not packaged for debian)
# install unzip so we can unpack deno
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED
RUN apt update && apt install -y unzip wget

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY downloader /tmp/downloader
RUN pip install /tmp/downloader && rm -r /tmp/downloader

# fetch deno binary from github release
ENV DENO_VERSION=2.9.6
RUN wget https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip
RUN unzip deno-x86_64-unknown-linux-gnu.zip && rm deno-x86_64-unknown-linux-gnu.zip
RUN mv deno /usr/local/bin/deno

# Install yt-dlp last as it changes often
RUN pip install 'yt-dlp[default]'

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "downloader", "--base-dir", "/mnt"]
