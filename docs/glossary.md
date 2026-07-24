# Glossary

Short definitions for the terms used throughout the [README](../README.md), the
[five-minute guide](launch.md), and the [technical guide](technical-guide.md), in the order a
newcomer usually meets them.

**OpenAPI contract**
The `openapi.yaml`/`.json` document you upload. It is the single source of truth SimuLoom
compiles everything else from — paths, operations, schemas, and examples all trace back to it.

**Simulation**
A workspace built from one uploaded contract: its generated data, scenarios, behavior profiles,
and deployment state. Most REST/MCP operations act on a specific simulation by ID.

**Synthetic data**
Fictional records generated from the contract's schemas — never real customer or production
data. Deterministic when you fix the seed, so the same input produces the same output.

**Mapping**
A compiled WireMock stub — one mapping per contract operation/response the runtime should serve.
"Compile" turns your contract and scenario into mappings; "deploy" pushes them into WireMock (or
the native runtime).

**Scenario**
A stateful business journey layered on top of the contract: named states, request handlers that
match specific inputs, and transitions between states (for example
`NOT_CREATED → PENDING → PAID → SHIPPED`). This is what lets the virtual service *remember* what
happened across requests, instead of returning the same canned response every time.

**Behavior profile**
A named configuration for how the virtual service should misbehave on purpose — added latency,
intermittent errors, or simulated outages — so you can test how your client handles a dependency
under stress without touching a real one.

**Revision / release**
A saved snapshot of a scenario (revision) and the promotion of a specific revision to be the
active, deployed version (release). Revisions are immutable once created; releases can be
promoted or rolled back.

**Edge case / pairwise case**
Automatically generated request variations used to validate contract coverage: edge cases probe
individual boundary and negative values (missing fields, out-of-range numbers); pairwise cases
combine multiple parameters together using pairwise combinatorial coverage instead of testing
every possible combination.

**Validation evidence**
The recorded proof that a set of requests were actually run against the simulation and what the
result was — separated by operation, scenario, boundary, negative, and pairwise coverage — so a
passing HTTP response can't hide an untested contract area. Exportable as JSON or HTML.

**Runtime**
The engine that actually serves virtualized HTTP responses: `wiremock` (delegates to a running
WireMock instance) or `native` (SimuLoom's own built-in runtime, backed by SQLite or an
in-memory store). Selected with `SIMULOOM_RUNTIME`.

**Audit log**
An append-only, optionally cryptographically signed record of who did what to a simulation and
when — every mutating REST/MCP call and authentication decision is recorded.

**REST**
The `/api/v1/*` HTTP API — what CI pipelines, scripts, and the operator console's browser calls
generally use.

**MCP (Model Context Protocol)**
The `/mcp` endpoint — the same application services exposed as tools and resources an MCP-capable
AI client (like Claude or another agent) can call directly, under the same authentication and
role checks as REST.

**Operator console**
The web UI at `/ui` — upload contracts, inspect simulations, design scenarios visually, run
validation, and review evidence without writing REST or MCP calls by hand.

**AI Copilot**
The optional, local-only, opt-in assistant (backed by Ollama) that can explain simulation state
and *propose* changes. It never mutates anything on its own — every proposal requires explicit
operator approval before it takes effect.
