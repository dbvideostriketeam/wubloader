FROM debian:13 AS build
# install python & pip, and tell python we're fine with messing with the system env
# install libpq-dev for postgres connectivity
RUN apt update && apt install -y --no-install-recommends python3 python3-pip gcc python3-dev libpq-dev \
    && rm /usr/lib/python3.13/EXTERNALLY-MANAGED \
    && rm -rf /var/lib/apt/lists/*

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY buscribe_api /tmp/buscribe_api
RUN pip install /tmp/buscribe_api && cp -r /tmp/buscribe_api/templates /templates \
    && rm -r /tmp/buscribe_api

FROM debian:13
# install python
# install libpq5 for postgres connectivity
RUN apt update && apt install -y python3 ca-certificates libpq5 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local /usr/local
COPY --from=build /templates /templates
ENTRYPOINT ["python3", "-m", "buscribeapi"]
