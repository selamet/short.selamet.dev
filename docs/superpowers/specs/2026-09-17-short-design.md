# short — Design Spec

Date: 2026-09-17
Status: approved for implementation planning

## 1. Overview

**short** is an open-source (MIT), self-hostable URL shortener for social media teams, built as a Django monolith. It is a multi-user product: users sign in with magic links, create or join workspaces, and manage short links on one shared short domain.

Differentiators visible in the product:

1. **Social card control** — per-link Open Graph title/description/image override with live preview; defaults fetched from the destination.
2. **Device-aware routing** — different destinations for iOS, Android and desktop, including native app deep links with web fallback.
3. **UTM builder with platform presets** — Instagram bio, Instagram story, TikTok, YouTube, Newsletter, Custom.

Plus analytics (total/unique clicks, time series, referrers, countries, cities, devices, OS, browsers, UTM breakdown, hour-of-day heatmap, bot filtering, CSV export), workspaces with roles, a REST API with workspace API keys, QR codes and CSV bulk import.

### Decisions

| Topic | Decision |
|---|---|
| Audience | Multi-user product with workspaces and roles (owner/admin/member) |
| Short domain | Single shared domain, configured via env. No custom domains in v1 |
| Clients | Web dashboard + REST API. Browser extension is phase 2 with its own spec |
| Analytics storage | Raw `ClickEvent` rows + daily rollups; raw rows purged after 90 days (configurable) |
| Phase 1 platform features | OG override + auto fetch, device routing + deep links, UTM presets |
| Phase 2 | Link-in-bio page, geo/language routing, A/B split, password links, expiry UI, browser extension |
| Auth | Magic link only, no passwords |
| Deployment | Single VPS. Docker Compose runs `web` and `worker` only; TLS termination and routing are done by the host's Caddy, which proxies the domain to a localhost port defined in a host-side compose override. PostgreSQL (behind PgBouncer in transaction pool mode, TLS) and Redis (TLS, ACL scoped to the `short:*` key space) are external shared services reached via `DATABASE_URL` / `CACHE_URL` |
| Frontend | Django templates + HTMX + Tailwind v4 (standalone CLI) + Chart.js. No SPA, no bundler |
| API | django-ninja under `/api/v1/` |
| Background work | Django 6 `django.tasks` API; `ImmediateBackend` in dev/test, `django-tasks-db` (`django_tasks_db.backend.DatabaseBackend`) in production |
| License | MIT |
| Language | Everything in the repo is English |

## 2. Project structure

### Infrastructure constraints
- PostgreSQL is reached through PgBouncer in transaction pool mode: `CONN_MAX_AGE = 0`, `DISABLE_SERVER_SIDE_CURSORS = True`, `sslmode=verify-full` in the URL.
- Redis is TLS-only (`rediss://`) and the app's ACL user may only touch keys matching `short:*`, on db 0. Django's built-in `RedisCache` with `KEY_PREFIX = "short"` is the only Redis client; no raw Redis usage outside the cache API.
- No server hostnames, IPs or credentials in the repository; everything comes from environment variables documented in `.env.example`.

```
short/
├── config/            # settings (base/dev/prod), urls, asgi/wsgi
├── apps/
│   ├── accounts/      # User (email only, no username), magic link flow
│   ├── workspaces/    # Workspace, Membership, Invitation, ApiKey, role checks
│   ├── links/         # Link, LinkTarget, Tag, OG override, UTM presets, services
│   ├── redirects/     # GET /<code> hot path, Redis cache, crawler handling
│   ├── analytics/     # ClickEvent, rollups, dashboard queries, export
│   ├── api/           # django-ninja routers, API key auth, v1 schemas
│   └── core/          # shared mixins, base62, validators, GeoIP service
├── templates/         # includes partials/ for HTMX swaps
├── assets/            # Tailwind input (assets/css/app.css), not served
├── static/            # built CSS (git-ignored), vendored HTMX and Chart.js, app.js
├── extension/         # phase 2, separate spec
├── docs/
├── compose.yaml       # web, worker (production; the host's Caddy terminates TLS)
├── compose.dev.yaml   # local postgres + redis
└── pyproject.toml     # uv, ruff, pytest
```

Rules:
- Each app has one responsibility. `redirects` depends only on `links` models and enqueues `analytics` tasks; it never renders dashboard templates.
- `api` has no models. Business logic lives in service functions inside `links`, `workspaces` and `analytics`; dashboard views and API routers call the same functions.
- Reserved short codes (`api`, `admin`, `auth`, `w`, `static`, `media`, `health`, ...) are a constant in `core`, not a model.

## 3. Data model

### accounts
- `User`: `email` (unique, USERNAME_FIELD), `display_name`, `theme` (system/light/dark), `is_staff`, `is_active`, `date_joined`. No password login.
- `MagicLink`: `user`, `token_hash` (SHA-256), `expires_at` (15 min), `used_at`, `ip_hash`, `created_at`.

### workspaces
- `Workspace`: `name`, `slug` (unique), `timezone`, `default_utm_preset`, `created_by`, `created_at`.
- `Membership`: `workspace`, `user`, `role` ∈ {owner, admin, member}; unique (workspace, user).
- `Invitation`: `workspace`, `email`, `role`, `token_hash`, `expires_at` (7 days), `accepted_at`, `invited_by`.
- `ApiKey`: `workspace`, `name`, `prefix` (first 8 chars, shown in lists), `key_hash`, `last_used_at`, `revoked_at`, `created_by`, `created_at`.

### links
- `Link`: `workspace`, `code` (unique; 7-char base62 by default or custom slug), `destination_url`, `title`, `favicon_url`, `note`, `status` ∈ {active, disabled, archived}, `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `og_title`, `og_description`, `og_image` (file or URL), `og_fetched_at`, `expires_at`, `max_clicks`, `click_count` (denormalized, updated by task), `created_by`, `created_at`, `updated_at`.
- `LinkTarget`: `link`, `platform` ∈ {ios, android, desktop}, `url`, `app_url` (deep link, optional), `fallback_url`; unique (link, platform). No rows when device routing is off.
- `Tag`: `workspace`, `name`, `color`; unique (workspace, name). `Link.tags` M2M.
- `ImportJob`: `workspace`, `file`, `status`, `total_rows`, `processed_rows`, `errors` (JSON), `created_by`, timestamps.

### analytics
- `ClickEvent`: `link`, `occurred_at`, `ip_hash` (daily salt), `country`, `city`, `device_type`, `os`, `browser`, `referrer_host`, `referrer_url` (query stripped), `utm_source/medium/campaign/content/term` (from the incoming request), `target_platform`, `is_bot`, `user_agent` (truncated to 256). Index (link, occurred_at). Purged after `CLICK_EVENT_RETENTION_DAYS` (default 90).
- `DailyLinkStat`: `link`, `date`, `clicks`, `unique_clicks`; unique (link, date).
- `DailyLinkBreakdown`: `link`, `date`, `dimension` ∈ {country, city, referrer, device, os, browser, utm_source, utm_medium, utm_campaign, target_platform}, `value`, `clicks`; unique (link, date, dimension, value).

Unique click definition: same `ip_hash` + `user_agent` for the same link within the same day counts once.

## 4. Redirect hot path and click pipeline

`GET /<code>`:

1. Served by a dedicated URL conf and a minimal middleware chain: no session, CSRF or auth middleware. Response carries `Cache-Control: no-store`.
2. Code is validated against the format and the reserved list; otherwise 404.
3. Redis lookup `link:<code>`. Value is a small JSON (destination, status, expiry, targets, UTM) or the sentinel `MISS` (negative cache, 60 s). On cache miss, read from PostgreSQL and cache for 1 h. The `links` service invalidates the key on any update, disable, archive or delete.
4. Target selection: detect platform from the user agent (ios/android/desktop). Use the matching `LinkTarget.url` if present, otherwise `destination_url`. Append stored UTM parameters without overriding parameters already present on the destination.
5. If the selected target has `app_url`, return a small `noindex` HTML page that attempts the deep link and falls back to `fallback_url` after 1.5 s.
6. Expiry (`expires_at`, `max_clicks`) is checked against cached values; expired links render the "link expired" page.
7. Enqueue `record_click(link_id, occurred_at, ip, user_agent, referrer, query_string, target_platform)`. This call never blocks the redirect.
8. Return `302 Found` (never 301, so every click is measured).

Social crawlers (facebookexternalhit, Twitterbot, WhatsApp, Slackbot, LinkedInBot, TelegramBot, Discordbot) receive an HTML page containing only the OG meta tags instead of a redirect. These requests are not counted as clicks. Other bot detection happens in the task, not the view.

Failure behavior: Cache unavailable → fall through to PostgreSQL and log. PostgreSQL unavailable → 503 with `Retry-After: 5`. Enqueue failure → click is dropped, redirect still happens, error goes to Sentry. Principle: redirect first, measurement second.

`record_click` task: hash IP with the daily salt, resolve country/city with GeoLite2, parse the user agent, flag bots, write `ClickEvent`, atomically increment `Link.click_count`, upsert `DailyLinkStat` and `DailyLinkBreakdown`. A nightly task recomputes the previous day's rollups from raw events as a consistency check.

## 5. Tasks and worker

Tasks use Django 6's `django.tasks` (`@task`, `.enqueue()`). Backend: `ImmediateBackend` in dev/test, `django_tasks_db.backend.DatabaseBackend` (package `django-tasks-db`) in production. The worker runs `manage.py db_worker` from the same image as `web`.

| Task | Trigger | Work |
|---|---|---|
| `record_click` | every redirect | geo, UA parse, bot flag, ClickEvent + rollup upsert |
| `fetch_og_metadata` | link create / destination change | fetch OG title, description, image, favicon; 5 s timeout, 2 MB cap, max 3 redirects, IP re-check after DNS |
| `check_safe_browsing` | link create / destination change, only if `SAFE_BROWSING_API_KEY` set | disable link and email owner if flagged |
| `generate_qr` | on demand | PNG + SVG to MEDIA, cached |
| `import_links_csv` | bulk import confirmed | validate and create rows, progress on `ImportJob` |
| `send_magic_link`, `send_invitation` | auth / invite | email sending, 3 retries |
| `rebuild_daily_stats` | nightly 02:00 | recompute yesterday's rollups from raw events |
| `expire_links` | every 10 min | disable links past `expires_at` or `max_clicks`, invalidate cache |
| `purge_click_events` | nightly | delete events older than retention in batches |
| `rotate_ip_salt` | nightly 00:00 | generate new daily salt, drop the previous one |

Scheduling: `django.tasks` has no scheduler. `supercronic` runs inside the worker container and calls `manage.py enqueue_scheduled <task>`; cron only triggers, work runs in the worker with retry semantics.

Error handling: tasks are idempotent (ClickEvent duplicate check on `link_id + occurred_at + ip_hash`, rollups are upserts). Retries: 3 attempts with exponential backoff. Permanent failures go to Sentry.

## 6. API and auth

### Magic link flow
- `POST /auth/login` accepts an email. Unknown emails create a user; sign-up and sign-in are the same form. Always respond with "Check your inbox" (no account enumeration).
- Token: 32 random bytes, sent plain in the email, stored as SHA-256 hash, valid 15 min, single use. Rate limit: 3 per email per 10 min, 20 per IP per hour (Redis).
- `GET /auth/verify/<token>` renders an auto-submitting confirmation page without consuming the token (keeps email link scanners from burning it); `POST /auth/verify/<token>` consumes the token, opens a session, redirects to workspace creation on first login or to invitation acceptance when arriving from an invite.
- Session auth for the dashboard and HTMX; standard Django CSRF.

### Authorization
- Every dashboard view and API endpoint runs in a workspace context. Dashboard URLs: `/w/<workspace-slug>/...`.
- Roles: **member** creates/edits links and views analytics; **admin** additionally invites members, manages tags and API keys; **owner** additionally deletes the workspace and transfers ownership.
- One `require_role(...)` decorator for views; service functions also check roles so API and dashboard enforce the same rules. Access to a workspace the user is not a member of returns 404.

### REST API (`/api/v1/`, django-ninja)
- Auth: `Authorization: Bearer short_...`. Key is hashed and looked up in `ApiKey`; `last_used_at` updated. A key belongs to one workspace, so endpoints carry no workspace parameter.
- Endpoints: `GET/POST /links`, `GET/PATCH /links/{code}`, `POST /links/{code}/archive`, `GET /links/{code}/stats` (summary + time series, date range params), `GET /links/{code}/qr`, `GET/POST /tags`, `GET /utm-presets`, `GET /me`.
- Rate limit: 120 requests/min per key → 429 with `Retry-After`.
- OpenAPI docs at `/api/v1/docs`.
- Error shape: `{"error": {"code": "slug_taken", "message": "..."}}`.
- No anonymous link creation.

## 7. Dashboard and frontend

Screens follow `docs/design/claude-design-prompt.md` (landing, preview page, error pages, auth, onboarding, links list, link form, link analytics, workspace analytics, QR modal, bulk import, workspace settings, account settings, global patterns).

- Templates: `base.html` → `dashboard/base.html` → pages. Every list, table and panel lives in `partials/` so full-page render and HTMX swap share the same markup. Django 6's built-in `{% partialdef %}` for inline partials.
- Full page loads: navigation between main pages, saving the link form. HTMX swaps: list filtering/search/pagination, row actions, slug availability check, OG preview refresh, analytics date range changes, QR modal, invite form. Modals and slide-overs load via `hx-get` into a single `#modal` container.
- No native `alert`/`confirm`; custom confirmation modal for destructive actions.
- Tailwind v4 standalone CLI, no Node. Design tokens from Claude Design go into `@theme`. Compiled CSS is not committed; built in Docker.
- Theme: `<html data-theme>`; user preference in `User.theme`; "system" resolved by an inline script before paint.
- Charts: vendored Chart.js. Each chart is `<canvas data-chart>` with its data in an adjacent `<script type="application/json">`; one `charts.js` renders all and re-renders on `htmx:afterSwap`.
- Copy-to-clipboard via a `data-copy` attribute and a toast.
- Forms: Django forms; inline errors + summary. HTMX form errors return 422 and re-swap the form partial.
- Accessibility: focus trap and Escape in modals, arrow keys in menus, `aria-label` on icon buttons, WCAG AA contrast.

Total custom JS: roughly 100 lines. No bundler.

## 8. Security and abuse

- Destination validation in the service layer: only `http`/`https`; reject the short domain itself, private IP ranges and `localhost`; OG fetch re-checks the resolved IP and follows at most 3 redirects. Domain blocklist from env and admin.
- Optional Google Safe Browsing check via task when `SAFE_BROWSING_API_KEY` is set.
- Rate limits (Redis fixed window, cache `add` + `incr`): magic link 3/email/10 min and 20/IP/hour; link creation 30/user/min and 120/key/min; redirect 20/IP/s; slug availability 60/user/min.
- Short codes: 7-char base62 generated with `secrets`; unknown codes are negatively cached.
- Privacy: IPs are never stored raw, only hashed with a daily salt kept until the end of the day plus a one-hour grace. User agents truncated to 256 chars. Referrer query strings dropped. Raw click events purged after retention. Deleting a user keeps workspace links with `created_by = NULL`.
- `client_ip` trusts only the `TRUSTED_PROXY_HOPS` entries closest to the app in `X-Forwarded-For`, so a client-supplied prefix can't be used to spoof the address rate limits key on.
- Production settings: HSTS, secure cookies, `SECURE_PROXY_SSL_HEADER` behind Caddy, CSP with nonces for inline scripts.
- API keys and magic link tokens stored hashed only; keys shown once at creation.
- Sentry optional via `SENTRY_DSN`. Admin at an env-configured path, staff only. Dependencies pinned with `uv.lock`; Dependabot enabled.

## 9. Testing and development workflow

- pytest + pytest-django + factory_boy. All Redis access goes through Django's cache API, so tests run on `LocMemCache`; `ImmediateBackend` for tasks.
- Unit tests for services: base62 generation and collisions, URL validation, UTM merging, platform detection, unique click counting, role checks.
- Integration tests for the redirect view: cache hit/miss, negative cache, device targets, deep link page, crawler OG page, expired link, Redis-down fallback.
- Task tests: `record_click` output, rollup idempotency.
- API tests via django-ninja `TestClient`: key auth, rate limit, error shape.
- View tests: non-member workspace access → 404; HTMX request → partial, normal request → full page.
- No browser tests in phase 1; Playwright arrives with the extension in phase 2.
- Coverage target above 90% for services and redirects, measured in CI, not enforced.
- Tooling: `uv`, `ruff` (lint + format), `pre-commit`, `django-environ`, `compose.dev.yaml` for local Postgres/Redis, `.env.example` documenting every variable.
- CI (GitHub Actions): ruff, pytest with a Postgres service container (cache is LocMemCache in tests), Docker build on every PR; image pushed to GHCR on merge to `main`.

### Workflow
- Every piece of work is a GitHub issue in English (context, scope, acceptance criteria), labeled `area:*`, `type:*`, `phase:*`, assigned to `selamet`.
- Branch `GH-<n>`, commits `GH-<n>-<type>: description`, PR linked with `Closes #n`, assigned to `selamet`, with a description of changes and how they were tested. No AI attribution anywhere.
- Issues are opened in spec order, each sized for a single PR.

### Phase 1 issue order
1. Project scaffold, settings, tooling, CI
2. accounts: User model, magic link flow, email templates
3. workspaces: Workspace, Membership, Invitation, roles, onboarding
4. links: models, services, validation, UTM presets, tags
5. redirects: hot path, cache, device routing, deep link page, crawler OG page
6. analytics: tasks, rollups, retention, salt rotation
7. dashboard: links list, link form, analytics screens (from Claude Design output)
8. api: django-ninja routers, API keys, rate limit, docs
9. QR codes and CSV bulk import
10. Deployment: Dockerfile, compose, Caddy, GeoLite2 setup, self-host docs
