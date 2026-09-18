# syntax=docker/dockerfile:1.7

# --- assets: build Tailwind CSS with the standalone CLI (no Node) ---------------
FROM debian:bookworm-slim AS assets
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scripts/tailwind.sh scripts/tailwind.sh
COPY assets assets
COPY templates templates
COPY apps apps
RUN bash scripts/tailwind.sh

# --- python deps ------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS deps
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

# --- runtime ------------------------------------------------------------------------
FROM python:3.13-slim-bookworm AS runtime
ARG TARGETARCH
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 curl && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app
# supercronic runs the crontab that drives the scheduled analytics/maintenance jobs
# (see docker/crontab and compose.yaml). Built for TARGETARCH -- amd64 or arm64,
# whichever this image's target platform is; BuildKit sets it automatically, and an
# arm64 build used to still fetch the amd64 binary pinned here, which then failed to
# execute at all: the worker's background supercronic start (see compose.yaml) hid
# that failure instead of surfacing it, so scheduled jobs silently never ran.
# Checksums verified by downloading each release asset and computing its SHA256
# locally (`shasum -a 256`), matching the digest GitHub's own release API reports for
# the same asset (https://api.github.com/repos/aptible/supercronic/releases/tags/v0.2.49).
ENV SUPERCRONIC_VERSION=v0.2.49
RUN case "$TARGETARCH" in \
        amd64) SUPERCRONIC_SHA256=a53ae236602c7338aba3fbaff40bda6300eae3b9fedb8261eb06cfe3724430c1 ;; \
        arm64) SUPERCRONIC_SHA256=02aa0cb229ba09050cba6638059dadb9eedc2276632ea43d6a57a2f8c1629dd5 ;; \
        *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && SUPERCRONIC_URL="https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${TARGETARCH}" \
    && curl -fsSLo /usr/local/bin/supercronic "$SUPERCRONIC_URL" \
    && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
    && chmod +x /usr/local/bin/supercronic
WORKDIR /app
COPY --from=deps /opt/venv /opt/venv
COPY --chown=app:app . .
COPY --from=assets --chown=app:app /app/static/css/app.css static/css/app.css
# A broken binary (wrong architecture, corrupt download) or a broken crontab must
# fail the build, not surface later as a worker that silently never runs its
# scheduled jobs -- see the note above.
RUN supercronic -test docker/crontab
RUN SECRET_KEY=build DATABASE_URL=sqlite:///build.db EMAIL_URL=smtp://build.invalid:25 \
    python manage.py collectstatic --noinput \
    && rm -f build.db && chmod +x docker/entrypoint.sh && mkdir -p /data/media && chown -R app:app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8000/health/ || exit 1
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "30", "--access-logfile", "-"]
