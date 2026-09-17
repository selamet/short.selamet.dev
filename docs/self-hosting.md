# Self-hosting short

short ships as a single Docker image that runs two processes from `compose.yaml`: `web` (gunicorn) and `worker` (`manage.py db_worker`, the Django tasks worker). TLS, the public port and the data stores are provided by the host.

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

## Notes

- `SECURE_SSL_REDIRECT` is on by default; `/health/` is exempt so plain-HTTP probes from the host keep working.
- Media uploads live in the `media` volume mounted at `/data/media`.
- Set `SENTRY_DSN` to enable error reporting.
