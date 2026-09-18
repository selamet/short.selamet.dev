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

Clicks can be tagged with a country and city if you point `GEOIP_PATH` at a GeoLite2 City database. This is entirely optional: leave `GEOIP_PATH` unset and the app runs exactly as before, with country and city left blank on every click. Only the `web` service resolves geography (in the redirect view, before a click is even enqueued -- see `apps.redirects.views` and `apps.analytics.geo`); `worker` never needs the file.

1. Sign up for a free MaxMind account and generate a license key at [maxmind.com](https://www.maxmind.com/en/geolite2/signup).
2. Download the **GeoLite2 City** database in `.mmdb` format and place it on the host, then bind-mount it into `web` in `docker-compose.override.yml` (next to the port mapping from step 2 above):

   ```yaml
   services:
     web:
       volumes:
         - /path/on/host/GeoLite2-City.mmdb:/data/GeoLite2-City.mmdb:ro
   ```

   A bind mount like this is what actually makes `/data/GeoLite2-City.mmdb` exist inside the container; setting `GEOIP_PATH` alone, with nothing mounted at that path, leaves every lookup failing to open the file.
3. Set `GEOIP_PATH=/data/GeoLite2-City.mmdb` in `.env` and restart the `web` service.

The database is licensed by MaxMind and updated periodically; it is never committed to this repository (`*.mmdb` is gitignored) and you are responsible for keeping your own copy up to date. Two things to know about updating it in place:

- The file is memory-mapped (`apps.analytics.geo` opens it once per worker process and reuses that handle for every click -- see `_get_reader`), so replace it by writing the new file elsewhere on the same filesystem and renaming it over the old path, never by truncating or overwriting the mounted file's own contents in place. A rename is atomic; a reader already holding the old file mapped keeps reading a complete, consistent copy of it until it next re-opens, and an in-place overwrite risks handing that reader a half-written file mid-read.
- A failed open (missing file, corrupt download, bad permissions) is cached for the life of the process -- `apps.analytics.geo._get_reader` only ever tries once per process, precisely so a bad database does not retry, and therefore hammer the filesystem, on every single click -- so it is only retried the next time that process starts. Restart `web` after fixing whatever made the open fail.

## Scheduled jobs

The `worker` container runs `supercronic` against `docker/crontab` alongside the task worker. Each line only enqueues work (`manage.py enqueue_scheduled <name>`); the worker process executes it, same as any other task. None of the four retries on failure -- the task backend in use here (`django_tasks_db`) has no retry layer -- so a failed run is logged and simply waits for the next scheduled run to catch up:

| Schedule | Job | What it does |
|---|---|---|
| `0 2 * * *` | `rebuild_daily_stats` | Recomputes yesterday's *and* the day before's rollups from raw clicks, correcting anything the incremental path missed. Redoing the previous day too is what lets a workspace west of UTC (whose local "yesterday" is still open when this run's UTC date is chosen) get corrected on the very next run rather than never. Refuses -- logging a warning and leaving the existing rollups alone -- a day older than `CLICK_EVENT_RETENTION_DAYS`, since its raw events are already gone and rebuilding it would otherwise zero it out. |
| `30 2 * * *` | `purge_click_events` | Deletes raw `ClickEvent` rows (and their identity rows) older than `CLICK_EVENT_RETENTION_DAYS`, in batches of `ANALYTICS_PURGE_BATCH_SIZE`, up to `ANALYTICS_PURGE_MAX_BATCHES` batches per table per run. A backlog bigger than that budget is finished across several nights rather than run unbounded, since the worker is serial and one very long purge would otherwise stall click recording and every other scheduled job behind it. |
| `0 0 * * *` | `rotate_ip_salt` | Makes sure the day's IP-hashing salt already exists right at midnight, without ever replacing one already in use. |
| every 10 minutes | `expire_links` | Disables links past `expires_at` or `max_clicks`. |
| `0 3 * * *` | `prune_db_task_results` | The existing django-tasks-db result cleanup, run directly rather than through `enqueue_scheduled` since it does its own work synchronously. |

Nothing in the `web` process schedules anything; if you run `worker` on a separate host or scale it to zero, these jobs simply stop running until it's back.

### Changing a workspace's timezone

`DailyLinkStat` and `DailyLinkBreakdown` rows are keyed by the *local* day a click fell on at the time it was recorded (`Workspace.timezone`, read by `apps.analytics.rollups.local_date`). Changing a workspace's timezone afterward does not retroactively re-bucket anything already rolled up: the days around the change stay keyed by whichever timezone was in effect when each click landed, so the rollups either side of the change can disagree with what the new timezone would have produced for the same raw events. This wave does not re-roll automatically. The repair path is manual: run `rebuild_daily_stats` (see `apps.analytics.tasks`) for the range of days the change affects, once the new timezone is in place, e.g. from a shell in the `worker` container:

```bash
python manage.py shell -c "
from apps.analytics.tasks import rebuild_daily_stats
from datetime import date, timedelta
day = date(2026, 1, 1)
while day <= date(2026, 1, 7):
    rebuild_daily_stats.enqueue(day.isoformat())
    day += timedelta(days=1)
"
```

## Notes

- `SECURE_SSL_REDIRECT` is on by default; `/health/` is exempt so plain-HTTP probes from the host keep working.
- Media uploads live in the `media` volume mounted at `/data/media`.
- Set `SENTRY_DSN` to enable error reporting.
