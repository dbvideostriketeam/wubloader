#!/bin/bash

mkdir models && cd models || exit
curl -LO http://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip
curl -LO http://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
curl -LO https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip

mkdir extracted
unzip vosk-model-en-us-0.22.zip -d extracted
unzip vosk-model-small-en-us-0.15.zip -d extracted
unzip vosk-model-spk-0.4.zip -d extracted
