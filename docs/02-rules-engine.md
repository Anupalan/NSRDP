# 02 Versioned rules engine (REC-01, design position D2)

## What is built

* `RuleVersion`: a rule is **data** (`definition.logic` in a small JSON-Logic-style
  language, see `src/nsrdp/rules/expr.py`), owned by a tenant, numbered per tenant and key,
  with `effective_from`/`effective_to`, author, **named approver** and approval time.
* Lifecycle: draft (needs `rules.author`) → approved (needs `rules.approve` at the rule's
  tenant and a different principal from the author) → optionally retired by setting an
  end date. Approved versions are immutable; changing a rule means a new version.
* No retroactive rules: a version cannot take effect before it is approved, and cannot be
  retired with a past date.
* Resolution: the most specific approved version in force at the evaluation time on the
  acting tenant's ancestor chain (State variation beats Centre rule; sibling States never
  see each other's rules).
* `Decision`: every evaluation stores rule key, **rule version id and number**, inputs,
  outcome, actor, subject and as-of time. Decisions are immutable and can be replayed.
* The expression language has no code execution; unknown operators are rejected at draft.

## Assumptions (SI proposal)

* Centre rules apply nationally unless a State publishes its own version of the same key.
* "Named approver" = the authenticated principal id; mapping to a person and office
  depends on the identity provider (TBC).

## Open clarifications (TBC)

| Item | Impact |
|---|---|
| Actual regulatory rules, thresholds and legal references | Entered as data by authorised users; none are in code. The test rule is illustrative only. |
| Who may author and approve rules at Centre vs State | `config/rbac.yaml` roles `rules_author` / `rules_approver` |
| Whether States may override national rules at all, or only extend them | Currently allowed; can be restricted by role grants |
| Whether approval needs eSign (SIG-01) | Approval hook is in one place (`approve_rule`) for adding a signature later |
| Retention period for decisions | Not set; decisions are kept |
