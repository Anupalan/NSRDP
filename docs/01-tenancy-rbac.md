# 01 Tenant and RBAC skeleton (PLT-01, REC-02)

## What is built

* `Tenant` tree with a materialised path. Levels and allowed parent/child pairs are read
  from `config/tenancy.yaml` (default: platform > centre > state > entity).
* Every tenant-owned table uses `TenantScoped` (or `ScopedByPath`). A SQLAlchemy session
  hook adds a subtree filter to every SELECT, UPDATE and DELETE, and fails closed when a
  session has no scope. On flush it stamps `tenant_path`, rejects rows outside scope and
  makes the owning tenant immutable.
* RBAC: permissions are what code checks; roles are bundles of permissions defined in
  `config/rbac.yaml`, each with the tenant levels where it may be granted. A role held at
  a tenant applies to that tenant's subtree.
* Segregation of duties (REC-02): no self-grant; static conflicting-role pairs in
  overlapping scope; dynamic conflicting-action pairs (`ensure_distinct_actors`, used by
  the rules engine for author vs approver).
* `/tenants` API showing the scope applied per request.

## Assumptions (SI proposal)

* A user acting at a tenant sees that tenant and its descendants, never siblings or
  ancestors. National (Centre) users therefore see all States.
* A Centre may own entities directly (configurable in `tenancy.yaml`).
* Data never moves between tenants; `tenant_id` is immutable.

## Open clarifications (TBC)

| Item | Where it is configured |
|---|---|
| Final tenant hierarchy and Centre-State operating model | `config/tenancy.yaml` |
| Entity types (facility, recycler, buyer, ...) | `config/tenancy.yaml` |
| Role catalogue and which roles conflict | `config/rbac.yaml` (current roles are placeholders) |
| Identity / e-KYC provider (integration #01) | `NSRDP_AUTH_MODE`; only a local `dev` header stub exists, default is disabled (501) |
| Whether States may see each other's data (e.g. cross-state vessel movements) | Not supported until agreed |

## Follow-ups

* PostgreSQL row-level security as a second, database-level layer under the ORM guard.
* Raw SQL is not covered by the ORM guard and is not allowed in domain code.
