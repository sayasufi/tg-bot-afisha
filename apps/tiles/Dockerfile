# Рендерер растровых тайлов: headless-chromium открывает /tilerender.html миниаппа (тот же
# maplibre-стиль, что у живой карты) и нарезает PNG-тайлы для машин без аппаратного WebGL.
# Базовый образ playwright уже содержит chromium — версия npm-пакета ДОЛЖНА совпадать с тегом.
FROM mcr.microsoft.com/playwright:v1.49.0-jammy

WORKDIR /tiles
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY package*.json ./
RUN npm install --omit=dev
COPY server.mjs ./

EXPOSE 8787
CMD ["node", "server.mjs"]
