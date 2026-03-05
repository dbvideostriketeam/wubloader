FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED
# install deno for yt-dlp js extraction (needed for youtube)
# deno is not packaged in the native debian repos, so we pull and unzip a release binary
RUN apt update && apt install -y unzip
ADD https://github.com/denoland/deno/releases/download/v2.7.3/deno-x86_64-unknown-linux-gnu.zip /deno.zip
RUN unzip /deno.zip -d /usr/local/bin/
RUN chmod +x /usr/local/bin/deno

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY downloader /tmp/downloader
RUN pip install /tmp/downloader && rm -r /tmp/downloader

# Install yt-dlp last as it changes often
RUN pip install 'yt-dlp[default]'

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "downloader", "--base-dir", "/mnt"]
