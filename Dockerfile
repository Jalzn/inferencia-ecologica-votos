FROM ghcr.io/astral-sh/uv:0.12.17 AS uv

FROM python:3.12-slim AS dataset
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pipeline/ pipeline/
COPY data/schemas/ data/schemas/
COPY scripts/release_tools.py scripts/release_tools.py
RUN UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --project pipeline --locked --no-dev

ARG DATASET_URL=https://github.com/Jalzn/inferencia-ecologica-votos/releases/download/v0.1.0/elections-2026-v3-20261029-93230d180f36.tar.gz
ARG DATASET_SHA256=e96ced89bb7af1e801be36ea2e0af1034abccd734e1bb6cb65c33e5e35598fd9
RUN .venv/bin/python scripts/release_tools.py fetch \
    --url "$DATASET_URL" --sha256 "$DATASET_SHA256" --output public-data
RUN .venv/bin/python -m elections.cli validate-release \
    --release public-data --require-full --deep-schema

FROM node:22-alpine AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY --from=dataset /app/public-data/ public/data/
ENV BASE_PATH=/
RUN npm run build

FROM caddy:2-alpine AS runtime
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/web/dist/ /srv/
ENV PORT=8080
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
