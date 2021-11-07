#!/bin/bash

VERSION=0.0.0

bash fetch_models.sh

docker build -f buscribe/Dockerfile -t buscribe:$VERSION .
docker build -f buscribe-api/Dockerfile -t buscribe-api:$VERSION .

docker build -f less/Dockerfile -t lessc
docker run --rm -v "$(pwd)"/buscribe-web:/buscribe-web lessc /buscribe-web/style.less > buscribe-web/style.css

docker build -f nginx/Dockerfile -t buscribe-web:$VERSION .