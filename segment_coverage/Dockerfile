FROM alpine:3.7
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
# freetype-dev and libpng-dev are required for matplotlib
RUN apk --update add py2-pip gcc python-dev musl-dev busybox-extras freetype-dev libpng-dev build-base libstdc++
#need to install these manually 
RUN ln -s /usr/include/locale.h /usr/include/xlocale.h \
	&& pip install numpy \
	&& pip install matplotlib

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY segment_coverage /tmp/segment_coverage
RUN pip install /tmp/segment_coverage && rm -r /tmp/segment_coverage

ENTRYPOINT ["python2", "-m", "segment_coverage"]
