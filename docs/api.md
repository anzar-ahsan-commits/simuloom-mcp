# SimuLoom scenario and validation API

SimuLoom v0.14.0 adds the bundled Operator Console and its additive dashboard APIs.
WireMock remains the default, and existing contract, dataset, profile, validation,
authentication, scenario, response, and artifact shapes remain compatible.

## REST endpoints

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| PUT | `/api/v1/simulations/{simulation_id}/scenarios/{scenario_id}` | operator | Create or replace a validated definition |
| GET | `/api/v1/simulations/{simulation_id}/scenarios/{scenario_id}` | viewer | Read its stored definition |
| GET | `/api/v1/simulations/{simulation_id}/scenarios/{scenario_id}/state` | viewer | Read live WireMock state |
| POST | `/api/v1/simulations/{simulation_id}/scenarios/{scenario_id}/compile` | operator | Generate mappings |
| POST | `/api/v1/simulations/{simulation_id}/scenarios/{scenario_id}/deploy` | operator | Compile, deploy, and initialize |
| POST | `/api/v1/simulations/{simulation_id}/scenarios/{scenario_id}/reset` | operator | Reset one managed scenario |
| POST | `/api/v1/scenarios/reset` | admin | Reset every scenario in the shared WireMock runtime |
| GET | `/api/v1/runtime` | viewer | Discover the selected adapter and its capabilities |
| GET | `/api/v1/session` | viewer | Discover the current subject and role for UI controls |
| GET | `/api/v1/simulations` | viewer | List dashboard-ready simulation summaries |
| POST | `/api/v1/simulations/from-contract` | operator | Create from a YAML/JSON multipart upload |

When `SIMULOOM_RUNTIME=native`, deployed virtual endpoints are served at
`/runtime/{simulation_id}/{service_path}` with the methods declared by their mappings. This
service-traffic façade is intentionally outside control-plane API-key middleware; protect or
restrict it separately at the ingress.

The OpenAPI UI at `/docs` contains complete generated request and response schemas.

## Operator Console

The console is served at `/ui` and its same-origin assets at `/ui/assets`. The static shell is
public so it can present credential entry, but every data request uses the authenticated
`/api/v1` API. Uploaded contracts are limited to 2 MiB, parsed with safe YAML loading, required
to be mapping objects, and passed through the same OpenAPI analysis used by JSON creation.

Console responses use a strict same-origin Content Security Policy, deny framing and MIME
sniffing, and send no referrer. Entered API keys use browser session storage rather than
persistent local storage. There are no third-party browser dependencies.

## Definition rules

A definition has a name, description, initial state, optional reset target, and one or more
named states. Each state contains request handlers. A handler supplies an exact request,
a deterministic response, and an optional next state. A handler without `new_state`
returns a state-specific response without changing state.

Scenario IDs use lowercase letters, numbers, and hyphens. Requests must match an operation in
the simulation's approved OpenAPI contract, and response status codes must be documented by
that operation. JSON responses are schema-validated when the contract supplies an inline or
locally referenced response schema.

Definitions are limited to 50 states, 50 handlers per state, 200 total handlers, and 1 MiB.
Absolute URLs, WireMock `/__admin` paths, ambiguous handlers, unknown states, and unsafe
response framing headers are rejected.

## Status codes

- `404`: simulation or scenario does not exist.
- `409`: a runtime operation requires a scenario to be deployed first.
- `422`: invalid ID, graph, contract operation, status, or response schema.
- `502`: runtime inspection, deployment, or reset failed.

## Scenario validation

`POST /api/v1/simulations/{simulation_id}/validation/plan` includes scenario cases after the
existing contract and dataset cases. For every handler in every reachable state, the planner
creates an independent replay: reset to the initial state, follow a shortest known path to the
required state, then invoke the target handler. A visited-state bound prevents cycles from
expanding forever, and plans are capped at 500 cases.

`POST /api/v1/simulations/{simulation_id}/validate` executes that plan and records these
optional scenario fields on each applicable case:

- `scenario_id`, `scenario_handler`
- `required_state`, `new_state`
- `reset_before`
- `actual_state_before`, `actual_state_after`

Evidence JSON and HTML include `state_coverage` and `transition_coverage` alongside existing
operation and scenario coverage. Only successful cases count toward those metrics. Any
reachable transition failure, declared-state coverage gap, or declared-transition coverage
gap fails the report. Declared but unreachable states therefore produce explicit incomplete
coverage. Full simulation deployment initializes every configured scenario to its declared
initial state.

## Edge-case validation options

Both validation request models accept these optional fields:

| Field | Default | Range | Purpose |
| --- | ---: | ---: | --- |
| `include_boundary_cases` | `false` | boolean | Execute valid values exactly at declared constraints |
| `include_negative_cases` | `false` | boolean | Execute one invalid mutation at a time when a 4xx/default response is documented |
| `max_edge_cases_per_operation` | `12` | 1-50 | Bound generated edge cases per operation |

Generated plan cases and evidence results expose `edge_polarity`, `edge_constraint`,
`edge_location`, and `edge_field`. Reports expose `boundary_coverage` and
`negative_coverage`. A failed edge case fails the overall report.

Supported request constraints are `required`, `minimum`, `maximum`, `exclusiveMinimum`,
`exclusiveMaximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, `enum`, and JSON type.
Request bodies and query/header/path parameters are supported where the constraint can be
represented as an exact HTTP request.

Arbitrary regular expressions are deliberately not executed. External references,
multipart bodies, and higher-strength combinations remain unsupported.

## Pairwise validation options

Both validation request models also accept:

| Field | Default | Range | Purpose |
| --- | ---: | ---: | --- |
| `include_pairwise_cases` | `false` | boolean | Execute a valid strength-two covering array |
| `max_pairwise_cases_per_operation` | `25` | 1-50 | Bound pairwise requests per operation |

Plan cases and evidence results expose `pairwise_assignments`, `pairwise_pair_ids`, and
`pairwise_total_pairs`. Reports expose `pairwise_coverage`. Coverage is calculated from pairs
exercised by successful cases. If the configured cap prevents complete coverage, the report
fails even when every executed request returned the expected response.

The generator supports at most 12 factors and four representative values per factor, with a
global 500-case limit. It uses valid enum, boolean, numeric, string-length, array-size,
optional/absent, nullable, and `oneOf`/`anyOf` alternatives. It does not combine multiple
invalid values; focused negative behavior remains part of v0.10 edge-case validation.

## MCP

Tools: `configure_scenario`, `inspect_scenario`, `compile_scenario`,
`deploy_scenario`, `reset_scenario`, and `reset_all_scenarios`.

The existing `plan_validation` and `run_validation` MCP tools accept the same edge-case
and pairwise options as REST.

Resources:

- `scenario://{simulation_id}/{scenario_id}/definition`
- `scenario://{simulation_id}/{scenario_id}/state`
- `runtime://current/capabilities`

The same viewer/operator/admin permissions apply to REST and MCP.

## Runtime selection

Set `SIMULOOM_RUNTIME` to `wiremock` (default) or `native`. `WIREMOCK_URL` selects the
WireMock Admin/service URL. `SIMULOOM_NATIVE_RUNTIME_URL` is the externally advertised native
façade base URL and defaults to `http://localhost:8000/runtime`.

Native storage settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIMULOOM_NATIVE_RUNTIME_STORE` | `sqlite` | Select durable `sqlite` or ephemeral `memory` |
| `SIMULOOM_NATIVE_RUNTIME_DB` | `{workspace}/runtime/native.db` | SQLite database path |
| `SIMULOOM_NATIVE_JOURNAL_LIMIT` | `1000` | Events retained per simulation, from 1 to 100000 |

The canonical runtime model covers exact or regex paths, exact/absent query and header
values, exact JSON bodies, deterministic JSON responses, delays, priorities, scenarios, and
request-journal evidence. WireMock artifacts stored by older versions are translated at the
adapter boundary. The native adapter isolates mappings, state, and journal events by
simulation ID.

SQLite native state survives restarts but remains single-node and is not a distributed
coordination mechanism for multiple application workers. Memory mode is deliberately lost on
restart. Raw non-JSON response bodies and advanced WireMock extensions are not yet portable
through the canonical model.
