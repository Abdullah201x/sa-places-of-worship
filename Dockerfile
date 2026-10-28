# syntax=docker/dockerfile:1

# Stage 1: Build the Vite frontend
FROM node:26-alpine AS builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# vite.config.js reads the CSP from ../deploy/Caddyfile.container
COPY deploy/ ../deploy/

ARG VITE_UMAMI_WEBSITE_ID=401cdcc1-cbfb-4962-8fc7-9d906f900bff
ENV VITE_UMAMI_WEBSITE_ID=$VITE_UMAMI_WEBSITE_ID

RUN npm run build

# Stage 2: Precompress once at build time, so the 2-vCPU VPS doesn't gzip
# ~20 MB of data for every new visitor; Caddy serves the .br/.gz copies.
FROM alpine:3.22 AS compress

RUN apk add --no-cache brotli gzip

COPY --from=builder /app/dist /srv/manara/dist

# Copy dataset files into the data directory
COPY summary.json \
     places_of_worship_sa.geojson \
     worship_gaps_sa.json \
     sa_boundary.geojson \
     mosque_sizes.json \
     mosque_anomalies.json \
     suggested_mosques_sa.geojson \
     /srv/manara/data/

RUN find /srv/manara -type f \( -name '*.html' -o -name '*.js' -o -name '*.css' -o -name '*.json' \
       -o -name '*.geojson' -o -name '*.svg' -o -name '*.txt' \) \
       -exec gzip -9 -k {} \; -exec brotli -q 11 -k {} \;

# Stage 3: Fast, secure Caddy edge container
FROM caddy:2.11-alpine

COPY deploy/Caddyfile.container /etc/caddy/Caddyfile
COPY --from=compress /srv/manara /srv/manara

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
