# Contributing

Thanks for helping build **short**.

## Local setup

    docker compose -f compose.dev.yaml up -d   # Postgres + Redis
    cp .env.example .env
    uv sync
    scripts/vendor.sh                           # htmx + chart.js (already committed, re-run to upgrade)
    scripts/tailwind.sh --watch &               # CSS
    uv run python manage.py migrate
    uv run python manage.py runserver

## Checks

    uv run ruff check . && uv run ruff format --check .
    uv run pytest

## Workflow

- Every change starts from a GitHub issue. Branch name `GH-<issue>`.
- Commit messages: `GH-<issue>-<type>: description` (`feat`, `fix`, `core`, `chore`, `refactor`, `test`, `docs`).
- Open a pull request that says `Closes #<issue>`, what changed and how it was tested.
- Everything in the repository is written in English.
- Tests first: add or update a test with every behavior change.
