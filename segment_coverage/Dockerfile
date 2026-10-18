FROM debian:13 AS build
# install python & pip, and tell python we're fine with messing with the system env
# install libpq-dev for postgres connectivity
# install libjpeg and zlib for image manipulation
# install libfreetype-dev and libpng-dev for matplotlib
RUN apt update && apt install -y --no-install-recommends python3 python3-pip gcc python3-dev libpq-dev libjpeg-dev zlib1g-dev libfreetype-dev libpng-dev \
    && rm /usr/lib/python3.13/EXTERNALLY-MANAGED \
    && rm -rf /var/lib/apt/lists/*

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY segment_coverage /tmp/segment_coverage
RUN pip install /tmp/segment_coverage && rm -r /tmp/segment_coverage

FROM debian:13
# install python
# install libpq5 for postgres connectivity
# install libjpeg and zlib for image manipulation
# install libfreetype-dev and libpng-dev for matplotlib
RUN apt update && apt install -y python3 ca-certificates libpq5 libjpeg-dev zlib1g-dev libfreetype-dev libpng-dev python3-packaging && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local /usr/local
LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "segment_coverage"]
