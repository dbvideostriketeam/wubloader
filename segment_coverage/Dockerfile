FROM debian:13
# install python & pip, and tell python we're fine with messing with the system env
# install libpq-dev for postgres connectivity
# install libjpeg and zlib for image manipulation
# install libfreetype-dev and libpng-dev for matplotlib
RUN apt update && apt install -y python3 python3-pip && rm /usr/lib/python3.13/EXTERNALLY-MANAGED
RUN apt update && apt install -y libpq-dev
RUN apt update && apt install -y libjpeg-dev zlib1g-dev
RUN apt update && apt install -y libfreetype-dev libpng-dev

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY segment_coverage /tmp/segment_coverage
RUN pip install /tmp/segment_coverage && rm -r /tmp/segment_coverage

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "segment_coverage"]
