# syntax=docker/dockerfile:1

# Stage 1: Build the Vite frontend
FROM node:22-alpine AS builder

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
COPY deploy/ ../deploy/

ARG VITE_UMAMI_WEBSITE_ID=401cdcc1-cbfb-4962-8fc7-9d906f900bff
ENV VITE_UMAMI_WEBSITE_ID=$VITE_UMAMI_WEBSITE_ID

RUN npm run build

# Stage 2: Fast, secure Caddy edge container
FROM caddy:2-alpine

COPY deploy/Caddyfile.container /etc/caddy/Caddyfile
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

EXPOSE 80

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
