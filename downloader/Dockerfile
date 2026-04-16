FROM debian:13 AS build
# deno is not packaged in the native debian repos, so we compile it from source
# as a rust compile from source is quite large, we do this in an intermediate image step
# rustup so we can get the version of rust that deno uses
# lsb-release and gnupg so llvm.sh works
# wget so we can get llvm.sh
# cmake and libglib2.0-dev per deno's CONTRIBUTING.md
# llvm.sh for LLVM 17, per deno's CONTRIBUTING.md
RUN apt update && apt install -y gnupg lsb-release rustup wget
RUN apt update && apt install -y cmake libglib2.0-dev
RUN wget https://apt.llvm.org/llvm.sh
RUN chmod +x llvm.sh
RUN ./llvm.sh 17
# install correct version of rust
RUN rustup install 1.92
# compile & install deno
RUN cargo install deno@2.7.12 --locked

FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED
# copy deno from build image for yt-dlp js extraction (needed for youtube)
COPY --from=build /root/.cargo/bin/deno /usr/bin/deno

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
