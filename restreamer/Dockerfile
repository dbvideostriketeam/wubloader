FROM alpine:3.7
RUN apk --update add py2-pip

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY restreamer /tmp/restreamer
RUN pip install /tmp/restreamer && rm -r /tmp/restreamer

# Add config file last as it changes most
COPY config.yaml /etc/wubloader.yaml

CMD python2 -m restreamer
