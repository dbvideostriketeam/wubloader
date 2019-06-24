# nginx container contains config that exposes all the various services metrics
FROM nginx:latest
ADD nginx/generate-config /
ENTRYPOINT ["/bin/sh", "-c", "/generate-config && nginx -g \"daemon off;\""]
