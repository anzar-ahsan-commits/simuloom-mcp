# Changelog

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
