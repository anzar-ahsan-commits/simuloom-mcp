# SimuLoom scenario API

SimuLoom v0.8.0 adds stateful scenarios beneath existing simulations. Existing v0.7.0
operations and schemas remain available without changes.

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

The OpenAPI UI at `/docs` contains complete generated request and response schemas.

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
- `502`: WireMock inspection, deployment, or reset failed.

## MCP

Tools: `configure_scenario`, `inspect_scenario`, `compile_scenario`,
`deploy_scenario`, `reset_scenario`, and `reset_all_scenarios`.

Resources:

- `scenario://{simulation_id}/{scenario_id}/definition`
- `scenario://{simulation_id}/{scenario_id}/state`

The same viewer/operator/admin permissions apply to REST and MCP.
