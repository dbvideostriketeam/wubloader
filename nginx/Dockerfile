# nginx container contains config that exposes all the various services metrics
FROM nginx:latest
ADD nginx/generate-config /
COPY thrimbletrimmer /etc/nginx/html/thrimbletrimmer
LABEL org.opencontainers.image.source https://github.com/ekimekim/wubloader
ENTRYPOINT ["/bin/sh", "-c", "/generate-config && nginx -g \"daemon off;\""]
