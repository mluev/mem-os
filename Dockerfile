# The dashboard is built first and copied in, so the runtime image needs no
# Node and the wheel keeps serving /ui exactly as a local checkout does.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/pnpm-lock.yaml* ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY web/ ./
COPY openapi.json /openapi.json
RUN pnpm build

FROM python:3.12-slim-bookworm AS runtime

# pg_dump for `memkit backup`, and the client must match the server major
# version or a custom-format dump is refused on restore.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl --fail -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    # CPU torch. The GPU wheels are several gigabytes and this runs on a VPS.
    UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu \
    # The embedding model is ~2 GB; a volume here keeps it across redeploys.
    HF_HOME=/models \
    MEMKIT_HOST=0.0.0.0 \
    MEMKIT_EMBED_DEVICE=cpu \
    PATH=/app/.venv/bin:$PATH

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
COPY integrations/ ./integrations/
COPY eval/ ./eval/
COPY --from=web /src/memkit/web_dist ./src/memkit/web_dist
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 memkit \
 && mkdir -p /models /data /backups /exports \
 && chown -R memkit:memkit /models /data /backups /exports /app
USER memkit

EXPOSE 8077
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8077/readyz || exit 1

CMD ["memkit", "serve"]
