# 03 Audit log and append-only event store (design position D3)

Foundation for TRC-01/TRC-02 (material and waste lineage) and for auditability (REC-06).

## What is built

* `events` table: one immutable fact per row, grouped into streams
  (`stream_type`, `stream_id`) with a per-stream sequence number.
* **Append-only, three layers**: ORM listeners refuse updates/deletes; database triggers
  refuse `UPDATE`/`DELETE` (PostgreSQL via migration 0003, SQLite in tests); every event
  carries `prev_hash` + `hash` (SHA-256 over canonical JSON), so out-of-band edits,
  deletions or reordering are detected by `verify_chain`.
* **Evidence references**: each event can cite files by `uri` + `sha256`. The evidence
  vault itself is a later item.
* **Corrections are new events** (`event_type="correction"`, `corrects_event_id`, a
  mandatory reason, optional evidence). `effective_events` applies the latest correction
  (or a void) and `project` folds events into derived state. Stored state is never truth.
* Optimistic concurrency (`expected_seq`), one tenant per stream, tenant scoping applies.
* **Audit log** (`nsrdp.events.audit`) writes `audit` streams keyed by target object. Role
  grants and rule draft/approve/retire are now audited.

## Assumptions (SI proposal)

* A per-stream hash chain is enough for tamper evidence in Sprint 1. Periodic anchoring of
  stream heads (e.g. signed daily digests, or eSign) can be added without a schema change.
* Event `occurred_at` is supplied by the caller (field time, e.g. from offline mobile
  capture); `recorded_at` is server time.

## Open clarifications (TBC)

| Item | Impact |
|---|---|
| Evidence vault product, location on GI Cloud, file size limits | Only references are stored now |
| Retention and archival period for events and audit records | None applied; nothing is deleted |
| Whether audit must also stream to a SIEM/SOC (integration #12) | Will be a connector (item 5) |
| Legal admissibility requirements for audit trails (e.g. signed digests) | Hash chain designed so anchoring can be added |
| Lineage event catalogue (recovered, weighed, dispatched, received, disposed, ...) | Defined with WS5; store is generic |
