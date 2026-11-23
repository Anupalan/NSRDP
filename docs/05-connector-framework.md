# 05 Connector framework (design position D4, REC-05)

## What is built

* **One hub** (`ConnectorHub`): the only way to call an external system. Every request and
  response is validated against the connector's contract. A connector without a contract
  cannot be called.
* **Contracts** in `contracts/<name>.yaml`: owner, status, requirement ID, and JSON Schema
  for each operation's request and response, plus an optional reconcile operation.
  `contracts/inventory.yaml` lists all 12 candidate interfaces from the handover with an
  owner and contract status. Drafted so far: eSign (#02), vessel data (#07),
  notifications (#10), SIEM (#12).
* **Stub generator**: a `StubConnector` is built from each contract and returns
  schema-valid responses from the contract's examples. It can inject transient or
  permanent failures. `python -m nsrdp.connectors.stubgen <name>` prints the simulator's
  request/response pairs for partner teams.
* **Contract-test harness**: `tests/contract/` runs every stub against its contract and
  checks the inventory (owner present, every contract listed). `check_adapter` is reused
  for live sandboxes when they exist.
* **Queue, retry with back-off, reconcile** (`connectors/outbox.py`): outbox rows are
  written in the same transaction as the business change; the dispatcher retries
  transient failures with capped exponential back-off and jitter; permanent failures or
  exhausted attempts mark the message dead and raise a `connector.exception` audit event
  naming the owner; the owner can requeue. `reconcile` re-queues anything the remote
  side does not hold. Idempotency keys are passed to the remote on every attempt.
* Mode per connector (`stub` default, `live` needs an explicitly registered adapter) via
  `config/connectors.yaml` or `NSRDP_CONNECTOR_<NAME>_MODE`.

## Assumptions (SI proposal)

* Each external system is wrapped once (system API); lifecycle steps compose them
  (process API); channels never call connectors directly.
* The dispatcher runs as a separate worker process using the same image.

## Open clarifications (TBC)

| Item | Where |
|---|---|
| Every interface in the inventory (all candidate, none confirmed) | `contracts/inventory.yaml` |
| Named owner per connector | Owners are roles until people are named |
| Retry counts and delays (depend on SLA targets) | `config/connectors.yaml` |
| eSign provider, document types, signing authority | `contracts/esign.yaml` |
| Notification provider and supported languages | `contracts/notifications.yaml` |
| SOC baseline and transport for SIEM feed | `contracts/siem.yaml` |
| Whether customs, pollution control, state systems have APIs at all | contracts pending |
| Exception routing channel (ticket system / service desk, OPS-01) | Currently an audit event |
