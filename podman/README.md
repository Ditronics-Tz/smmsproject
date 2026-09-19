# SMMS Backend — Podman Setup (Fedora WSL)

Django 5.0 + DRF on `python:3.12-slim-bookworm` (uv-built venv), with
PostgreSQL 15, Redis 7, Celery worker + Celery beat. Image runs as non-root
`django:1000` via `entrypoint.sh`.

## Requirements

- Fedora WSL (WSL2) with rootless Podman: `sudo dnf install -y podman podman-compose`
- Verified with Podman 5.8.7 + podman-compose 1.6.0
- A `.env` file (copy `.env.example`); at minimum `SECRET_KEY` and `DB_PASSWORD`
  (the app refuses to start without them)

## Installation

```bash
cd ~/projects/smmsproject          # or /mnt/d/projects/adhim-kitchen/smmsproject
cp .env.example .env               # set SECRET_KEY, DB_PASSWORD, hosts
```

## Environment

See `.env.example` (full list). Key variables:

| Variable | Purpose / default |
|---|---|
| `DEBUG` | `False` (dev: `True`) |
| `SECRET_KEY` | **required**, no default |
| `DB_NAME` / `DB_USER` / `DB_PASSWORD` | postgres creds (`smmsdb`/`postgres`/required) |
| `DB_HOST` / `DB_PORT` | `db` / `5432` inside the network |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | host/origin allow-lists |
| `API_BASE_URL` | default `http://127.0.0.1:8000` |
| `DJANGO_SUPERUSER_*` | optional dev superuser seed |

Never commit `.env`; nothing secret is baked into the image.

## Build

```bash
podman compose build
```

## Run

```bash
podman compose up -d
```

Startup order is enforced: `db`/`redis` (healthchecks) → `web`
(`entrypoint.sh` waits for Postgres, runs `migrate`, `collectstatic`,
optional superuser) → `celery`/`celery-beat` (wait for web setup flag,
verify `migrate --check`).

API: http://localhost:8000 · Health: http://localhost:8000/health
(detailed, admin-only: `/status` checks DB + Redis).

## Stop

```bash
podman compose down          # keep data
podman compose down -v       # also delete DB/Redis data (destructive)
```

## Logs / Status

```bash
podman compose ps
podman compose logs -f
podman compose logs -f web
```

## Database

- PostgreSQL 15 (`postgres:15-alpine`), named volume `postgres_data`,
  published localhost-only as `127.0.0.1:5439:5432`.
- Redis 7 (`redis:7-alpine`), named volume `redis_data`,
  published localhost-only as `127.0.0.1:6381:6379` (6380 is held by a stale
  WSL relay in this environment; container port unchanged).
- Services talk over isolated network `smmsapi_network` via names
  (`db:5432`, `redis:6379`); only the app port (8000) is required.

Migrations (automatic on `web` start; manual form):

```bash
podman compose exec web python manage.py migrate --noinput
podman compose exec web python manage.py createsuperuser
podman compose exec web python manage.py collectstatic --noinput
```

Backups: `make backup-db` / `make restore-db FILE=...` (pg_dump/psql).
Never run resets/drops/seeds automatically.

## Ports

| Service | Container | Host (localhost only) |
|---|---|---|
| web (Django) | 8000 | 8000 |
| db (Postgres) | 5432 | 5439 |
| redis | 6379 | 6381 |

No conflict with the frontend (host :3000).

## Troubleshooting

- `web` crash-loop: check `SECRET_KEY`/`DB_PASSWORD` are set —
  `podman compose logs web`.
- `migrate --check` failures in workers: wait for `web` setup to finish;
  workers retry automatically.
- Port clash: `ss -lntp | grep -E '8000|5439|6381'`.
- Fresh start: `podman compose down -v` (deletes DB data!) then `up -d`.
- Windows checkout: prefer `~/projects/` (WSL fs); `/mnt/d/...` is slower.
