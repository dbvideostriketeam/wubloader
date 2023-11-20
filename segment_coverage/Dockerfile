FROM alpine:3.14
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev file make busybox-extras jpeg-dev zlib-dev

# Try to get wheels working
RUN pip install --upgrade pip wheel

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent==22.10.2

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application

# freetype-dev and libpng-dev are required for matplotlib
RUN apk add freetype-dev libpng-dev build-base libstdc++ postgresql-dev postgresql-libs
# need to install these manually
RUN ln -s /usr/include/locale.h /usr/include/xlocale.h \
	&& pip install numpy \
	&& pip install matplotlib
COPY segment_coverage /tmp/segment_coverage
RUN pip install /tmp/segment_coverage && rm -r /tmp/segment_coverage

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "segment_coverage"]
