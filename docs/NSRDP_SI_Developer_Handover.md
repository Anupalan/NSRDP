# NSRDP System Integrator: Developer Handover

**Design canvas:** https://claude.ai/artifact/3cFmyXpCoZBZQPvfpBWvag (5 artboards, private until shared)
**Basis:** `NSRDP_REOI_Evaluation_Framework.docx`, built from REOI screenshots. Issuing authority: DGMA, Ministry of Ports, Shipping and Waterways, Government of India.
**Status:** Design proposal for bid preparation. Not an approved specification.

---

## 1. Read this first: what is fact, proposal, or open

| Label | Meaning | Examples |
|---|---|---|
| **Source** | Stated in the REOI framework. Mandatory. | The 30 requirements (PLT, LC, REG, WRK, TRC, MIS, ESG, MKT, BD, INT, INF, SEC, SIG, CHG, OPS). |
| **Recommended** | The framework's own suggestion, not official REOI. | REC-01 to REC-08; 70/30 weighting; gates 0–6; risk register. |
| **SI proposal** | Added by this design. Needs approval at Gate 1. | Six-layer architecture, design positions D1–D5, the interface list. |
| **TBC** | Not known. Do not assume. | Timelines, SLA targets, volumes, prices, eligibility, scoring method, contract terms. |

Do not hard-code any TBC value. Make it configuration, or stub it behind an interface.

---

## 2. Product in one paragraph

NSRDP is a national regulatory and traceability platform for ship recycling. It orchestrates lifecycle workflows (facility authorization to recycling permission), keeps trusted registries (facilities, vessels, workers, materials, waste), records worker identity and welfare data, and traces material and waste back to the originating vessel. It adds MIS and ESG analytics, a recovered-materials marketplace and a ship acquisition module, across Centre and State tenants, hosted on GI Cloud.

Lifecycle: **Upstream** (facility authorization, vessel registration, IHM, acquisition) → **Midstream** (surveys, inspections, certifications, permissions, worker records) → **Downstream** (material recovery, waste traceability, disposition, marketplace, ESG).

---

## 3. Workstreams and ownership

| WS | Scope | Responsibility | Requirement IDs |
|---|---|---|---|
| WS1 | A Core platform | Multi-tenant web portal, mobile app, tenant model | PLT-01, 02, 03 |
| WS2 | B Lifecycle | Versioned workflows and rules: facility, vessel, IHM, survey, inspection, certificate, permission | LC-01 to 05, REC-01 |
| WS3 | C Registries | Facility, vessel, worker, material, waste registries; migration; retention | REG-01 to 04, REC-03 |
| WS4 | D Worker identity | Unique worker ID; safety, welfare, training, skills, health records | WRK-01 to 03 |
| WS5 | E Traceability | Material and waste lineage to originating vessel | TRC-01, 02 |
| WS6 | F Analytics and ESG | Dashboards, MIS, KPIs, decision support, ESG | MIS-01, 02, ESG-01 |
| WS7 | G Marketplace and acquisition | E-marketplace, business development module | MKT-01, BD-01 |
| WS8 | H Enablement and technology | Integration, hosting, security, eSign, training, O&M, exit | INT-01 to 03, INF-01, SEC-01, SIG-01, CHG-01, OPS-01, REC-02, 04 to 08 |

---

## 4. Architecture (SI proposal)

Six layers. Domain modules deploy independently but share identity, rules engine, registry core and audit log.

| Layer | Components | Requirements |
|---|---|---|
| L1 Channels | Web portal, mobile app (offline capture and sync), public registry views, partner APIs | PLT-01, 02, REG-01, INT-02 |
| L2 Access and experience | Identity, RBAC, segregation of duties; eSign service; notifications and multilingual | REC-02, SIG-01, REC-08 |
| L3 Domain modules | Facility authorization; vessel and IHM; survey and inspection; certification and permissions; worker identity and records; material and waste lineage; marketplace; ship acquisition | LC, WRK, TRC, MKT, BD |
| L4 Platform services | Workflow and versioned rules; registry and master data; evidence vault and audit log; event bus; analytics and ESG | REC-01, REG, TRC, MIS, ESG |
| L5 Integration hub | API gateway and catalogue; adapters; IoT gateway; migration pipelines | REC-05, INT-01 to 03, REC-03 |
| L6 Infrastructure | GI Cloud hosting; backup and DR; observability and service desk | INF-01, REC-04, OPS-01 |

**Cross-cutting:** security and privacy (SEC-01, REC-06), auditability, DevSecOps, portability (REC-07).

### Design positions to ratify at Gate 1

| ID | Decision | Developer implication |
|---|---|---|
| D1 | Modular core, not a service sprawl | Domain modules share platform services. Do not create a service per entity. |
| D2 | Rules as versioned configuration | No regulatory logic in code. Rules are data, versioned, with a named approver. Every decision records the rule version used. |
| D3 | Append-only lineage events | Material and waste movements are immutable events with evidence. Corrections are new events, never updates. State is derived. |
| D4 | One hub for all external interfaces | No point-to-point calls. Each connector has a contract, a contract test and an owner. |
| D5 | Privacy-by-design for worker data | Purpose limitation, lawful basis or consent, field-level access, retention rules, decided before building WS4. |

### Multi-tenancy (PLT-01)

Hierarchy: Platform → Centre → State → Entity (facility, recycler, buyer). Tenant hierarchy, roles and the Centre–State operating model are **open**. Build tenant scoping as a first-class concept in the data model and every query from day one. Retrofitting it is expensive.

---

## 5. Integration inventory (all candidate, none confirmed)

Pattern: system APIs wrap each external system once; process APIs compose them into lifecycle steps; channels call only process and experience APIs. External outages must not lose a transaction: queue, retry with back-off, reconcile, route exceptions to an owner.

| # | System | Purpose | Pattern | Req | Open question |
|---|---|---|---|---|---|
| 01 | Identity / e-KYC provider | User and worker identity | OAuth2, REST | WRK-01 | Lawful basis for worker identity |
| 02 | eSign provider | Sign and validate certificates, permissions | REST, XML | SIG-01 | Provider, document types, signing authority |
| 03 | GI Cloud | Hosting, network, baselines | Infra | INF-01 | Environment, security baseline, network limits |
| 04 | State maritime and port authorities | State tenant onboarding and data exchange | Tenant + API | INT-01 | Operating model |
| 05 | State pollution control / environment bodies | Waste-stream records | REST, file | TRC-02 | Does an API exist? |
| 06 | Customs and port community systems | Vessel arrival and cargo, lineage start | REST, batch | TRC-01 | Does an API exist? |
| 07 | Class societies and vessel databases | Validate vessel particulars | REST, file | REG-02 | Access |
| 08 | Payment and settlement | Marketplace payments | REST, webhook | MKT-01 | Are payments in scope? |
| 09 | IoT devices and gateways | Telemetry and events | MQTT, HTTPS | INT-03 | Use cases, devices, standards |
| 10 | SMS, e-mail, messaging | Alerts and expiry notices | REST | REC-08 | Provider |
| 11 | Legacy and offline data | One-time and delta migration | Batch, ETL | REC-03 | Sources, formats, quality |
| 12 | SIEM / SOC feeds | Logs, alerts, incidents | Syslog, REST | REC-06 | Baseline |

**Per-interface lifecycle:** inventory and agree → contract and sandbox (or simulator) → build with contract tests → rehearse at Gate 3 → operate and monitor.

**Developer rule:** until an interface is confirmed, code against a stub that implements the proposed contract. Do not block on the real system.

---

## 6. Requirement traceability

Every requirement needs evidence at each gate. Track status with: **C** compliant, **PC** partial, **NC** non-compliant, **CS** compliant with customization, **TBC** clarification required.

| ID | Requirement | WS | Layer | Basis |
|---|---|---|---|---|
| PLT-01 | Secure, scalable multi-tenant web portal | WS1 | L1 | Source |
| PLT-02 | Mobile application | WS1 | L1 | Source |
| PLT-03 | End-to-end design, development, integration, implementation, O&M | WS1 | All | Source |
| LC-01 | Facility authorization workflows | WS2 | L3 | Source |
| LC-02 | Vessel registration | WS2 | L3 | Source |
| LC-03 | IHM inventory and lifecycle | WS2 | L3 | Source |
| LC-04 | Surveys and inspections | WS2 | L3 | Source |
| LC-05 | Certifications and recycling permissions | WS2 | L3 | Source |
| REG-01 | Facility registries (National, State) | WS3 | L4 | Source |
| REG-02 | Vessel registry | WS3 | L4 | Source |
| REG-03 | Worker registry | WS3 | L4 | Source |
| REG-04 | Material and waste-stream registries | WS3 | L4 | Source |
| WRK-01 | Unique digital worker identification | WS4 | L3 | Source |
| WRK-02 | Worker safety and welfare records | WS4 | L3 | Source |
| WRK-03 | Training, skills and health records | WS4 | L3 | Source |
| TRC-01 | Material traceability to originating vessel | WS5 | L3, L4 | Source |
| TRC-02 | Waste traceability to originating vessel | WS5 | L3, L4 | Source |
| MIS-01 | Configurable dashboards and MIS | WS6 | L4 | Source |
| MIS-02 | KPIs, analytics, decision support | WS6 | L4 | Source |
| ESG-01 | ESG monitoring | WS6 | L4 | Source |
| MKT-01 | Recovered-materials e-marketplace | WS7 | L3 | Source |
| BD-01 | Business development / ship acquisition module | WS7 | L3 | Source |
| INT-01 | Centre–State enablement | WS8 | L5 | Source |
| INT-02 | API integrations | WS8 | L5 | Source |
| INT-03 | IoT readiness | WS8 | L5 | Source |
| INF-01 | GI Cloud hosting | WS8 | L6 | Source |
| SEC-01 | Cybersecurity | WS8 | All | Source |
| SIG-01 | eSign | WS8 | L2 | Source |
| CHG-01 | Training and knowledge transfer | WS8 | n/a | Source |
| OPS-01 | O&M | WS8 | L6 | Source |
| REC-01 | Configurable rules and workflow engine, audit logs, versioned rules | WS2 | L4 | Recommended |
| REC-02 | RBAC and segregation of duties | WS8 | L2 | Recommended |
| REC-03 | Migration, reconciliation, archival, retention | WS3 | L5 | Recommended |
| REC-04 | Availability, DR, backup, restoration | WS8 | L6 | Recommended |
| REC-05 | API catalogue, docs, sandbox, test harness | WS8 | L5 | Recommended |
| REC-06 | Security testing, remediation, incident response | WS8 | L6 | Recommended |
| REC-07 | Interoperability, portability, exit plan | WS8 | All | Recommended |
| REC-08 | Accessibility, multilingual, assisted workflows | WS8 | L2 | Recommended |

---

## 7. Delivery gates

Durations are **TBC**. Gate 0 is where the TBCs below get resolved.

| Gate | Name | SI delivers | Exit evidence |
|---|---|---|---|
| 0 | Discovery and baseline | Process maps, rule inventory, interface inventory, dependency schedule, volume and NFR baseline | Signed baseline; clarifications resolved |
| 1 | Architecture and design approval | Solution and data architecture, workflow catalogue, threat model, hosting and integration plan | Design authority approves D1–D5 |
| 2 | Prototype / pilot | Vertical slice; one registry; one lineage chain; inspection workflow; dashboard | Demonstration accepted |
| 3 | Build and integration | Increments per workstream; connectors with contract tests; migration rehearsals | Traceability shows build coverage |
| 4 | UAT and security assurance | UAT; independent security test and fixes; performance and DR tests | Acceptance criteria met |
| 5 | Rollout and adoption | Pilot and staged State onboarding; role-based training; cutover; hypercare | Users productive; hypercare exit |
| 6 | O&M and improvement | Service desk, SLA reporting, quarterly review, maintained exit pack | SLA met; exit pack current |

**Governance:** Tier 1 steering committee; Tier 2 programme board; Tier 3 design and rules authority. Rule approval is kept separate from delivery.

---

## 8. Non-functional baseline

All numeric targets are **TBC**. Implement as configuration and test against placeholders until set.

- Availability, RTO, RPO, incident response and resolution, change lead time: `[TARGET]`
- Expected volumes (facilities, vessels, workers, users, transactions, inspections, certificates, material and waste records): not provided
- Accessibility and languages: required by REC-08; standard and language list TBC
- Retention, archival, deletion, data residency, hosting classification: TBC
- Worker-health data scope, consent or lawful basis, access and retention: TBC. **Do not build WS4 health fields until resolved.**

---

## 9. Open clarifications that block build

1. Detailed process maps and legal rules per recycling stage.
2. User groups, hierarchy, roles, permissions, Centre–State operating model.
3. Which government systems exist, have APIs, and are documented.
4. Data ownership, hosting classification, residency, archival, backup, DR, deletion.
5. Expected volumes.
6. Worker-health data scope, privacy and consent rules.
7. Traceability model: identifiers, events, evidence documents, reconciliation expectations.
8. IoT use cases, devices, telemetry, standards, connectivity.
9. Marketplace governance, eligibility, verification, transaction model, disputes, payments in scope or not.
10. Ship acquisition module scope, data sources, approvals, external integrations.
11. GI Cloud environment, procurement, security baselines, network constraints.
12. eSign providers, document types, signing authority, validation, certificate lifecycle.
13. Migration sources, formats, quality, cleansing responsibility, acceptance.
14. SLA metrics, hours, severity, targets, penalties, windows, escalation.
15. IP ownership, source-code escrow, configuration ownership, reusable components, exit provisions.
16. Evaluation method, qualification criteria, minimum technical score, commercial scoring, tie-breakers, contract terms.

---

## 10. Risks developers can reduce directly

| Risk | Rating | Developer-level control |
|---|---|---|
| Unclear workflow ownership | High | Rules versioned with approver and effective date (D2) |
| Integration dependencies | High | Stubs, contract tests, simulators (section 5) |
| Sensitive worker records | High | Field-level access, purpose limitation, audit of every read (D5) |
| Traceability data quality | High | Unique identifiers, event validation, evidence capture, reconciliation queue (D3) |
| Vendor lock-in | High | Open interfaces, documented export formats (REC-07) |
| Cybersecurity and uptime | High | Threat model, security tests in CI, restore drills |
| Marketplace liability | Medium–High | Keep transaction boundary configurable until policy is set |
| Scope ambiguity, adoption, cost escalation | High | Requirement-ID tagging on every story; change control |

---

## 11. Suggested first sprint

1. Tenant and RBAC skeleton with Platform, Centre, State, Entity scoping.
2. Rules engine with versioning and decision-record logging.
3. Audit log and append-only event store.
4. Registry core with unique identifier scheme (vessel, facility, worker, material, waste).
5. Connector framework with stub generator and contract-test harness.
6. CI with security scanning; GI Cloud-compatible deployment baseline.
7. Tag every backlog item with a requirement ID from section 6.

---

## 12. Canvas file map

| Artboard | File | Content |
|---|---|---|
| 1 Mandate and workstreams | `Main.dc.html` | Commitments, WS1–8, lifecycle |
| 2 Reference architecture | `Architecture.dc.html` | Layers, D1–D5, tenancy |
| 3 Integration hub | `Integrations.dc.html` | Interface inventory, lifecycle, gating questions |
| 4 Delivery and governance | `Delivery.dc.html` | Gates 0–6, tiers, team, SLA skeleton |
| 5 Evaluation, risk, TCO | `Assurance.dc.html` | Criteria evidence map, risk register, cost lines |

Design system: SENTINEL (navy `#0b1c33`, action blue `#2f5fe0`, canvas `#f4f6f9`, IBM Plex Sans and Mono). Colours were taken from its README by hand because it has no `tokens.json`.

## 13. Caveat

The source is screenshots of the REOI, not the full document. Eligibility, scoring, timelines, contract terms, SLAs, volumes and detailed specifications are absent. Verify everything in this handover against the official procurement document before using it for formal decisions.
