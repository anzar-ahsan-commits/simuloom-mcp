# Changelog

## 0.40.0 - Local AI and Operational Resilience

- Added opt-in Ollama structured-output scenario drafting with contract validation and no mutation
  or tool-execution authority.
- Added a Team Hub console for workspace membership, jobs, integrations, and secret metadata.
- Added encrypted per-workspace integration signing keys.
- Persisted integration circuit state across application restarts.
- Added an application job worker with atomic claims and restart requeue behavior.
- Migrated the durable platform schema to version 2 with backward-compatible startup migration.

## 0.39.0 - Modern Platform Release Hardening

- Added MCP parity and resources for workspaces, GitOps, jobs, secrets, and integrations.
- Completed security, compatibility, documentation, packaging, and live deployment gates.

## 0.38.0 - Resilient Automation

- Added idempotent transient delivery retries, exponential backoff, circuit cooldowns, and
  interrupted-job recovery.

## 0.37.0 - Durable Background Jobs

- Added persisted queued/running/succeeded/failed jobs for workspace backups and GitOps snapshots.

## 0.36.0 - Managed Workspace Secrets

- Added master-key encrypted secrets with metadata-only list operations and no plaintext reads.

## 0.35.0 - Safe Outbound Integrations

- Added exact-host allowlists, HTTPS enforcement, HMAC signatures, idempotency keys, and bounded
  delivery behavior.

## 0.34.0 - Production Deployment

- Added non-root container execution, upgrade-safe volume ownership, public readiness probes, and
  Kubernetes deployment assets.

## 0.33.0 - Durable Observability

- Persisted orchestration counters and added consolidated admin diagnostics.

## 0.32.0 - GitOps Automation

- Added deterministic integrity-protected snapshots, a validation/drift CLI, REST export, and CI
  package gates.

## 0.31.0 - Team Workspaces

- Added durable workspaces, creator ownership, membership-scoped discovery, role management, and
  last-admin protection.

## 0.30.0 - Durable Platform Store

- Added a WAL-enabled, migration-managed SQLite metadata foundation with schema readiness checks.

## 0.29.0 - Guided Scenario Workflows

- Replaced advanced command-string prompts with accessible labeled dialogs and validation.

## 0.28.0 - Consolidation and Hardening

- Made workspace artifact writes atomic and durable, with process-coordinated transactions that
  prevent lost scenario updates across local workers.
- Introduced explicit workspace format metadata and schema compatibility checks while adopting
  existing workspaces automatically.
- Added authenticated runtime and workspace readiness diagnostics.
- Coordinated audit-chain appends across processes and synchronized them to durable storage.
- Hardened workspace backup/restore by excluding control files and rejecting duplicate targets
  before any content is written.
- Constrained caller-provided request IDs and added failure, concurrency, traversal, schema, and
  multi-writer regression tests.

## 0.27.0 - Workspace Backup and Restore

- Added bounded deterministic control-plane backups and merge-safe restore.
- Rejects traversal, symlinks, oversized archives, and every overwrite before writing.

## 0.26.0 - Orchestration Observability

- Added bounded low-cardinality counters through JSON, Prometheus text, and MCP.

## 0.25.0 - Event and Webhook Orchestration

- Added safe inbound topic transitions, payload journals, REST webhook ingestion, and MCP publishing.

## 0.24.0 - Virtual Scenario Clocks

- Added deterministic timeout transitions driven by explicit virtual-time advancement.

## 0.23.0 - Scenario Fault Injection

- Added deterministic delays and empty-response, connection-reset, and malformed-response faults.

## 0.22.0 - Parameterized Scenario Instances

- Added declared template placeholders with strict missing/extra parameter validation.

## 0.21.0 - Reusable Scenario Templates

- Added workspace-level templates extracted from immutable revisions and contract-safe instantiation.

## 0.20.0 - Environment Promotion

- Added exact-revision promotion between simulations with target contract and ETag validation.

## 0.19.0 - Policy Audit Evidence

- Added a separate tamper-evident domain-event hash chain for policy and orchestration actions.

## 0.18.0 - Release Approval Gates

- Added opt-in approvals, immutable review decisions, breaking-change policy, and guarded deployment.

## 0.17.0 - Scenario Release Management

- Added semantic revision comparison with explicit breaking-change indicators.
- Added immutable deployment records pinning revision, ETag, mapping fingerprint, actor, and time.
- Added exact-revision deployment and rollback-as-a-new-release through REST and MCP.
- Updated runtime state and reset behavior to follow the deployed revision rather than a newer draft.
- Added designer revision comparison, release visibility, exact deployment, and rollback controls.

## 0.16.0 - Safe Scenario Editing

- Added immutable scenario revision history with author and timestamp metadata.
- Added strong ETags and optional `If-Match` optimistic concurrency checks for saves and
  restores; stale editors receive a structured `409` response.
- Added REST and MCP history inspection and restore operations. Restore creates a new revision
  and never deletes earlier history.
- Added designer revision indicators, unsaved-change warnings, history inspection, conditional
  saves, and explicit reload-or-overwrite conflict handling.
- Preserved existing clients and lazily adopts pre-v0.16 scenarios as revision 1.

## 0.15.0 - Visual Scenario Designer

- Added a native SVG scenario graph with automatic state and transition layout.
- Added form-based state, handler, request matcher, response, and transition editing.
- Added scenario JSON import/export plus save, compile, deploy, state, and reset controls.
- Added unreachable-state, terminal-state, and self-transition graph diagnostics.
- Added approved contract-operation and stored-scenario discovery endpoints.
- Added viewer read-only behavior and safe text-only SVG label rendering.
- Added designer API, graph diagnostics, UI asset, and regression coverage.

## 0.14.0 - Operator Console

- Added a bundled responsive operator console at `/ui` with no frontend build dependency.
- Added runtime health, simulation summaries, contract upload, and workflow controls.
- Added generate, compile, deploy, profile, validation, evidence, export, and scenario actions.
- Added session role discovery and viewer-aware control disabling.
- Added bounded YAML/JSON OpenAPI uploads and simulation-listing REST endpoints.
- Added strict console CSP, framing, MIME-sniffing, and referrer security headers.
- Added console API, static asset, authentication-boundary, and end-to-end workflow tests.

## 0.13.0 - Durable Native Runtime

- Added SQLite-backed persistence for native mappings, scenario state, and request journals.
- Added automatic native runtime restoration after application and container restarts.
- Added configurable memory or SQLite storage and bounded per-simulation journal retention.
- Added storage and persistence metadata to REST and MCP runtime capabilities.
- Added schema-version validation, simulation isolation, retention, and restart coverage.
- Preserved WireMock as the default runtime and retained all v0.12 API behavior.

## 0.12.0 - Pluggable Runtime Adapters

- Added a vendor-neutral mapping model and runtime adapter protocol.
- Added runtime selection through `SIMULOOM_RUNTIME=wiremock|native`.
- Added an in-process native runtime with simulation isolation, scenarios, delays, reset,
  request matching, and a request journal.
- Added a native HTTP façade at `/runtime/{simulation_id}/{path}`.
- Added REST and MCP capability discovery while retaining legacy WireMock response fields.
- Preserved WireMock as the default adapter and kept v0.11 APIs and artifacts compatible.

## 0.11.0 - Pairwise Test Generation

- Added deterministic strength-two covering arrays for valid OpenAPI request values.
- Added enum, boolean, numeric, string, array, optional, nullable, and union factors.
- Added exact priority-three WireMock mappings and bounded case generation.
- Added opt-in REST and MCP pairwise validation controls.
- Added pairwise coverage to JSON and HTML evidence, including explicit cap shortfalls.
- Added a synthetic pricing-checkout example and real WireMock integration coverage.

## 0.10.0 - Contract Edge-Case Validation

- Added deterministic boundary and negative requests derived from approved OpenAPI schemas.
- Added support for required, numeric, string-length, array-size, enum, and type constraints.
- Added exact priority-two WireMock mappings backed only by documented success and 4xx responses.
- Added opt-in REST and MCP validation controls with per-operation case limits.
- Added boundary and negative coverage to JSON and HTML evidence.
- Added a copy-paste constraint-validation example and real WireMock integration coverage.

## 0.9.0 - Scenario Validation Evidence

- Added bounded shortest-path validation replays for every reachable scenario handler.
- Added runtime assertions for required and resulting WireMock scenario states.
- Added declared state and transition coverage to JSON and HTML evidence reports.
- Added full-deployment initialization of each configured scenario's initial state.
- Added branch, failure, unreachable-state, regression, and live WireMock coverage.

## 0.8.0 - Stateful Scenario Orchestration

- Added validated, deterministic multi-state scenario definitions.
- Added WireMock scenario compilation, deployment, live inspection, and reset operations.
- Added REST and MCP interfaces with viewer/operator/admin authorization.
- Added fingerprinted scenario artifacts to portable simulation bundles.
- Added a complete synthetic order-lifecycle example.
- Preserved all v0.7.0 contract, dataset, validation, profile, authentication, and audit behavior.

## 0.7.0

- Added generic OpenAPI synthetic cases, validation evidence, portable bundles, role-scoped
  authentication, and tamper-evident audit events.
