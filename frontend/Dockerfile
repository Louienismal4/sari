# syntax=docker/dockerfile:1

FROM node:22.23.1-alpine3.24 AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29.4-alpine

LABEL org.opencontainers.image.title="Sari-Sari Frontend" \
      org.opencontainers.image.description="Local static frontend and backend reverse proxy" \
      org.opencontainers.image.source="sari"

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["wget", "--quiet", "--output-document=-", "http://127.0.0.1:8080/healthz"]
