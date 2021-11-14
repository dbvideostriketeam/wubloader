#!/bin/bash

VERSION=0.0.0

bash fetch_models.sh

docker build -f buscribe/Dockerfile -t buscribe:$VERSION .
docker build -f buscribe-api/Dockerfile -t buscribe-api:$VERSION .
docker build -f professor-api/Dockerfile -t professor-api:$VERSION .

docker build -f docker-less/Dockerfile -t lessc .
docker run --rm -v "$(pwd)"/buscribe-web:/buscribe-web lessc /buscribe-web/style.less > buscribe-web/style.css
docker run --rm -v "$(pwd)"/professor:/professor lessc /professor/style.less > professor/style.css

docker build -f nginx/Dockerfile -t buscribe-web:$VERSION .
