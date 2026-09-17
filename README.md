# short

Open-source, self-hostable URL shortener built for social media teams.

**short** is a Django monolith that goes beyond plain redirects:

- **Social card control** – override Open Graph title, description and image per link, with a live preview.
- **Device-aware routing** – send iOS, Android and desktop visitors to different destinations, including native app deep links.
- **UTM builder with platform presets** – one click for Instagram bio, Instagram story, TikTok, YouTube or newsletter campaigns.
- **Analytics** – total and unique clicks, time series, referrers, countries, devices, browsers, hour-of-day heatmap, bot filtering, CSV export.
- **Workspaces** – invite teammates with owner/admin/member roles.
- **REST API** – workspace API keys, OpenAPI docs, browser extension support.

## Status

Early development. Follow the [issues](../../issues) for the roadmap and `docs/superpowers/specs/` for the design.

## Quick start (development)

    docker compose -f compose.dev.yaml up -d
    cp .env.example .env
    uv sync && scripts/tailwind.sh
    uv run python manage.py migrate
    uv run python manage.py runserver

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and [docs/self-hosting.md](docs/self-hosting.md) to run it in production.

## Stack

Django 6 · PostgreSQL · Redis · django-tasks · HTMX · Tailwind CSS · django-ninja

## License

[MIT](LICENSE)
