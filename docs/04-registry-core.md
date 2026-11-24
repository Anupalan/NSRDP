# 04 Registry core and identifier scheme (REG-01..04)

## What is built

* One `registry_records` table for facility (REG-01), vessel (REG-02), worker (REG-03),
  material and waste (REG-04). Each kind's attributes, types, required flags and
  validators are defined in `config/registry.yaml`; unknown attributes are rejected.
* **National identifier**: `<prefix>-<kind code>-<zero-padded sequence>-<check>`, e.g.
  `IN-VSL-00000042-NN`. Two ISO 7064 MOD 97-10 check digits (as in IBAN) catch typing
  errors. Prefix, kind codes and width are configuration. IDs carry no State or facility,
  so they never change when ownership moves.
* National per-kind sequences (`registry_sequences`, row-locked on PostgreSQL).
* **External identifiers** (e.g. IMO number) are unique nationally through a database
  constraint, so two States cannot register the same ship. IMO numbers are checked with
  the standard IMO check digit.
* Material and waste records must name a registered **origin vessel** (lineage anchor
  for TRC-01/TRC-02).
* Register and amend need `registry.write` at the tenant; every change is an event in
  stream `registry/<id>` (history) plus an audit entry. External IDs cannot be amended.

## Worker data and D5

* **No worker-health fields** (WRK-03 is blocked by D5 / privacy TBC). The worker kind
  holds only an opaque `identity_ref` from the identity provider and an employment status.
* A guard rail rejects any worker attribute whose name matches a health-related pattern
  (`worker_forbidden_attribute_patterns`), so health fields cannot be added by config.
* No names, national ID numbers or contact details are stored until purpose, lawful basis
  or consent, field-level access and retention are agreed.

## Assumptions (SI proposal)

* Vessels are national records: a facility in one State may record material from a vessel
  registered by another. Only the existence and kind of the origin vessel are checked
  across tenants; its details stay scoped.
* The current record is a snapshot; the event stream is the history.

## Open clarifications (TBC)

| Item | Where |
|---|---|
| Official identifier format and prefix, whether DGMA has an existing scheme | `config/registry.yaml` `id_scheme` |
| Attribute lists per registry (facility, vessel, material, waste) | `config/registry.yaml` |
| Material taxonomy and waste classification codes | `category`, `waste_stream` are free text for now |
| Worker identity: lawful basis, provider, which identifiers may be stored | Blocked on D5 |
| Legacy data migration (REC-03) and how existing IDs map | Later item; external IDs table supports mapping |
| Retention periods per registry | Not applied |
