FROM node:17-alpine AS less
RUN npm install less -g
ADD buscribe-web /assets
WORKDIR /assets
RUN lessc style.less > style.css

# nginx container contains config that exposes all the various services metrics
FROM nginx:latest
ADD nginx/generate-config /
COPY --from=less /assets /etc/nginx/html/buscribe
COPY thrimbletrimmer /etc/nginx/html/thrimbletrimmer
LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["/bin/sh", "-c", "/generate-config && exec nginx -g \"daemon off;\""]
