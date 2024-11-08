FROM node:17-alpine AS less
RUN npm install less -g
ADD buscribe-web /assets
WORKDIR /assets
RUN lessc style.less > style.css

FROM node:23.1-alpine AS thrim
ADD thrimbletrimmer /assets
WORKDIR /assets
RUN npm install
RUN npm run build

# nginx container contains config that exposes all the various services metrics
FROM nginx:latest
ADD nginx/generate-config /
COPY --from=less /assets /etc/nginx/html/buscribe
COPY --from=thrim /assets/dist /etc/nginx/html/thrimbletrimmer
LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["/bin/sh", "-c", "/generate-config && exec nginx -g \"daemon off;\""]
