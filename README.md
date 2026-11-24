# NSRDP platform core

National Ship Recycling Digital Platform (REOI by DGMA, MoPSW). This repository holds the
System Integrator's platform core. It is a **design proposal for bid preparation, not an
approved specification**. See [docs/](docs/README.md) for assumptions and open (TBC) items.

## Stack

Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16. Containerised, configured only
through environment variables and YAML policy files in `config/`.

## Run the tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock && pip install --no-deps -e .
pytest                                    # SQLite in memory
NSRDP_TEST_DATABASE_URL=postgresql+psycopg://nsrdp:nsrdp@localhost/nsrdp_test pytest
```

## Run locally in containers

```bash
docker compose up --build    # API on http://localhost:8000/healthz
```

## Migrate a database

```bash
NSRDP_DATABASE_URL=postgresql+psycopg://... alembic upgrade head
```
