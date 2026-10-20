# Build a partir da raiz do repositório.
FROM node:22-alpine AS build
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# URL de tiles do mapa (opcional; padrão OpenStreetMap)
ARG VITE_TILE_URL=""
ENV VITE_TILE_URL=$VITE_TILE_URL
RUN npm run build

FROM caddy:2.10-alpine
COPY docker/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
