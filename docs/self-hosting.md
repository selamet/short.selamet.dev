# Self-hosting short

short ships as a single Docker image that runs two processes from `compose.yaml`: `web` (gunicorn) and `worker` (`manage.py db_worker`, the Django tasks worker, alongside `supercronic` running a small crontab of scheduled jobs -- see below). TLS, the public port and the data stores are provided by the host.

## What you need

- A Linux host with Docker and Docker Compose.
- PostgreSQL 15+ reachable over TLS. Connection pooling through PgBouncer in transaction mode is supported and recommended; the settings already disable persistent connections and server-side cursors.
- Redis 7+ reachable over TLS. The app only ever touches keys prefixed `short:`, so an ACL user restricted to that key space is enough.
- A reverse proxy that terminates TLS and forwards to the container port with `X-Forwarded-Proto: https` and `X-Forwarded-Host` set (Caddy, nginx, Traefik).
- An SMTP account. Magic links are the only way to sign in, and production refuses the console email backend.

## Steps

1. Clone the repository on the host and copy `.env.example` to `.env`. Fill in at least:

   | Variable | Example |
   |---|---|
   | `SECRET_KEY` | a long random string |
   | `ALLOWED_HOSTS` | `sho.rt` |
   | `SHORT_DOMAIN` | `sho.rt` |
   | `CSRF_TRUSTED_ORIGINS` | `https://sho.rt` |
   | `DATABASE_URL` | `postgresql://short_app:PASSWORD@db.example.com:5432/short?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt` |
   | `CACHE_URL` | `rediss://short:PASSWORD@redis.example.com:6379/0` |
   | `EMAIL_URL` | `smtp+tls://USER:PASSWORD@smtp.example.com:587` |
   | `DEFAULT_FROM_EMAIL` | `short <short@example.com>` |
   | `ADMIN_URL_PATH` | a non-guessable path segment |

   `sslrootcert` must point at a CA bundle inside the container; the image ships Debian's bundle at `/etc/ssl/certs/ca-certificates.crt`. Loopback hosts are added to `ALLOWED_HOSTS` automatically for the container health check.

2. Publish the web port to the host only. Create `docker-compose.override.yml` next to `compose.yaml`:

   ```yaml
   services:
     web:
       ports:
         - "127.0.0.1:8107:8000"
   ```

3. Point the reverse proxy at that port. Caddy example:

   ```
   sho.rt {
       encode gzip
       reverse_proxy 127.0.0.1:8107
   }
   ```

4. Start the stack. Migrations run on every start of `web` because `RUN_MIGRATIONS=1` is set in `compose.yaml`.

   ```bash
   docker compose -f compose.yaml -f docker-compose.override.yml up -d --build
   curl -s http://127.0.0.1:8107/health/
   ```

   The health endpoint reports `{"status": "ok", "database": "ok", "cache": "ok"}` when both stores are reachable.

## Updating

```bash
git pull --ff-only
docker compose -f compose.yaml -f docker-compose.override.yml up -d --build --remove-orphans
```

This repository's own `Deploy` workflow does exactly that over SSH with a key restricted to a forced command, after the `CI` workflow succeeds on `main`. To reuse it, set the `DEPLOY_SSH_KEY`, `DEPLOY_HOST` and `DEPLOY_USER` secrets and the `PUBLIC_URL` variable in your fork.

## Optional: click geography

Clicks can be tagged with a country and city if you point `GEOIP_PATH` at a GeoLite2 City database. This is entirely optional: leave `GEOIP_PATH` unset and the app runs exactly as before, with country and city left blank on every click.

1. Sign up for a free MaxMind account and generate a license key at [maxmind.com](https://www.maxmind.com/en/geolite2/signup).
2. Download the **GeoLite2 City** database in `.mmdb` format and place it somewhere the container can read, e.g. mounted at `/data/GeoLite2-City.mmdb`.
3. Set `GEOIP_PATH=/data/GeoLite2-City.mmdb` in `.env` and restart the `web` and `worker` services.

The database is licensed by MaxMind and updated periodically; it is never committed to this repository (`*.mmdb` is gitignored) and you are responsible for keeping your own copy up to date.

## Scheduled jobs

The `worker` container runs `supercronic` against `docker/crontab` alongside the task worker. Each line only enqueues work (`manage.py enqueue_scheduled <name>`); the worker process executes it, same as any other task:

| Schedule | Job | What it does |
|---|---|---|
| `0 2 * * *` | `rebuild_daily_stats` | Recomputes yesterday's rollups from raw clicks, correcting anything the incremental path missed. |
| `30 2 * * *` | `purge_click_events` | Deletes raw `ClickEvent` rows (and their identity rows) older than `CLICK_EVENT_RETENTION_DAYS`, in batches of `ANALYTICS_PURGE_BATCH_SIZE`. |
| `0 0 * * *` | `rotate_ip_salt` | Makes sure the day's IP-hashing salt already exists right at midnight, without ever replacing one already in use. |
| every 10 minutes | `expire_links` | Disables links past `expires_at` or `max_clicks`. |
| `0 3 * * *` | `prune_db_task_results` | The existing django-tasks-db result cleanup, run directly rather than through `enqueue_scheduled` since it does its own work synchronously. |

Nothing in the `web` process schedules anything; if you run `worker` on a separate host or scale it to zero, these jobs simply stop running until it's back.

## Notes

- `SECURE_SSL_REDIRECT` is on by default; `/health/` is exempt so plain-HTTP probes from the host keep working.
- Media uploads live in the `media` volume mounted at `/data/media`.
- Set `SENTRY_DSN` to enable error reporting.
