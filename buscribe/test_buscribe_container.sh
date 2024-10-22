#!/bin/bash

docker run \
  --rm \
  -v /srv/wubloader/segments/:/mnt/ \
  buscribe:0.0.0 \
  loadingreadyrun \
  --start-time='2021-11-05T00:00' \
  --end-time='2021-11-07T00:00' \
  --database=postgresql://vst:flnMSYPRf@mula.lan:6543/buscribe_lrr \
  --model=/usr/share/buscribe/vosk-model-en-us-0.22/
#  --model=/usr/share/buscribe/vosk-model-small-en-us-0.15/
