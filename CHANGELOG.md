# Changelog

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
