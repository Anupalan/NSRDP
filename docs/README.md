# NSRDP engineering notes

Labels follow the developer handover: **Source** (REOI, mandatory), **Recommended**
(framework suggestion), **SI proposal** (needs Gate 1 approval), **TBC** (unknown; never
hard-coded, always configuration or a stub).

## Stack choice (SI proposal)

| Choice | Why |
|---|---|
| Python 3.12, FastAPI | Widely known, easy to staff in India, typed request models, OpenAPI for free (partner APIs, INT-02). |
| PostgreSQL 16 | Open source, available as a managed or self-run service on GI Cloud (MeghRaj) and any other cloud; JSONB for versioned rule data; row-level security available as a second tenancy layer. |
| SQLAlchemy 2 + Alembic | One ORM hook enforces tenant scope on every query; migrations are plain, reviewable files. |
| OCI container, config via env | Runs on GI Cloud VMs or Kubernetes without change; no vendor-managed services required (REC-07 portability / exit). |
| One modular codebase | D1: modules share identity, rules, registry and audit services; no service per entity. |

Tests run on SQLite for speed and on PostgreSQL in CI.

## Sprint 1 items

| # | Item | Requirement IDs | Notes |
|---|---|---|---|
| 1 | Tenant and RBAC skeleton | PLT-01, REC-02 | [01-tenancy-rbac.md](01-tenancy-rbac.md) |
