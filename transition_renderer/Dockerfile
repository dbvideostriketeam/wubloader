FROM node:25.2-alpine

RUN apk add --no-cache chromium ffmpeg ca-certificates font-liberation setpriv

WORKDIR /app
COPY transition_renderer/ ./
RUN npm install
RUN npm run build

ENV REMOTION_BROWSER_EXECUTABLE=/usr/bin/chromium
LABEL org.opencontainers.image.source=https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["node", "out/tools/render-assets.mjs"]
CMD ["/mnt"]
