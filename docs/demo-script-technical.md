# Demo script: technical (30-45 min)

Audience: engineers, QA, platform/SRE. Uses raw REST via `curl`, the operator console, and MCP
side by side to show they're the same governed simulation underneath. Pair with
[demo-script-narrative.md](demo-script-narrative.md) if the room is mixed technical/business.

Everything below uses the checked-in [order-lifecycle example](../examples/order-lifecycle/) so
it is copy-pasteable and reproducible — no external services, no real data.

## Before the room fills

```bash
git clone https://github.com/anzar-ahsan-commits/simuloom-mcp.git
cd simuloom-mcp
docker compose up --build -d
until curl --fail --silent http://localhost:8000/api/v1/readyz; do sleep 1; done
```

- Open three browser tabs: `http://localhost:8000/ui`, `http://localhost:8000/docs` (Swagger),
  and this repo's `examples/order-lifecycle/` folder in your editor.
- Open two terminals: one for `curl`/`jq`, one kept free for live output.
- Decide up front whether the AI Copilot segment (§9) runs live against Ollama
  (`SIMULOOM_AI_ENABLED=true`, model pulled — see [README §Optional local AI](../README.md#optional-local-ai-scenario-drafting))
  or is narrated from screenshots. Don't debug Ollama connectivity live; decide before the room fills.
- Have a rollback: `docker compose down --volumes && docker compose up --build -d` resets to zero
  in under a minute if a live step goes sideways.

Install `jq` if you don't have it — every command below assumes it.

## 1. Pitch (2 min)

> "Your frontend is ready. The order API is not. The shared payment sandbox is flaky and can't
> reproduce the failure you need to fix before Friday's demo. SimuLoom turns an approved OpenAPI
> contract into a virtual service that remembers business state, fails in controlled ways on
> purpose, and proves what was tested — through a web console, REST, and MCP, all backed by the
> same application services."

## 2. Architecture in 60 seconds (2 min)

Show [README's Architecture section](../README.md#architecture). One sentence per box:
**Contract → Compiler → {synthetic data, stateful scenarios, evidence} → Runtime (WireMock or
native)**, with the console, REST API, and MCP all calling the same services underneath — nothing
is console-only or API-only.

```bash
curl --fail http://localhost:8000/api/v1/health | jq .
curl --fail http://localhost:8000/api/v1/readyz | jq .
```

## 3. Contract → synthetic data (5 min)

Upload the contract and create a simulation:

```bash
SIMULATION_ID=$(curl -fsS -X POST http://localhost:8000/api/v1/simulations/from-contract \
  -F "name=Order Lifecycle Demo" \
  -F "contract=@examples/order-lifecycle/openapi.yaml;type=application/yaml" |
  jq -r '.id')
echo "$SIMULATION_ID"
```

Generate deterministic synthetic data, then fetch it back to inspect a record — generation and
inspection are separate calls, matching the console's separate "Generate data" / "Inspect data"
buttons:

```bash
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/data" \
  -H 'Content-Type: application/json' -d '{"records": 25, "seed": 1207}' | jq '.record_count'
curl -fsS "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/data" | jq '.records[0]'
```

Talking point: every field is schema-derived from the contract, marked `synthetic: true`, and
**deterministic** — same seed, same data, every run. Same result live in the console:
**02 Simulations → select it → "1. Synthetic data" → Generate data / Inspect data**.

## 4. Compile and deploy (2 min)

```bash
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/compile" | jq '.mapping_count'
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/deploy" \
  -H 'Content-Type: application/json' -d '{"reset_existing": false}' | jq .
curl -fsS http://localhost:8080/__admin/mappings | jq '.mappings | length'
```

Console equivalent: **"2. Runtime bundle" → Compile → Deploy**. This is a real WireMock instance
now serving contract-derived responses at `localhost:8080`.

## 5. Stateful scenario — the centerpiece (8-10 min)

Open `examples/order-lifecycle/scenario.yaml` in your editor and point at the four states:
`NOT_CREATED → PENDING → PAID → SHIPPED`. This is what turns a static mock into something that
remembers what happened.

Configure, compile, and deploy the scenario:

```bash
SCENARIO=$(python3 -c "
import json, yaml
print(json.dumps(yaml.safe_load(open('examples/order-lifecycle/scenario.yaml'))))
")
curl -fsS -X PUT "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle" \
  -H 'Content-Type: application/json' -d "$SCENARIO" | jq '.definition.states | length'
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/compile" | jq .
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/deploy" | jq .
```

Switch to the console: **03 Scenarios → select the simulation → order-lifecycle**. Point at the
state graph — it's a real SVG, and every state node is keyboard-navigable
(`role="button" tabindex="0"`), not just decoration.

Now exercise the same order through its whole lifecycle and show the state actually changes:

```bash
curl -fsS -X POST http://localhost:8080/orders \
  -H 'Content-Type: application/json' -d '{"itemId":"ITEM-SYN-001","quantity":1}' | jq .

curl -fsS http://localhost:8080/orders/ORD-SYN-001 | jq '.status'   # PENDING

curl -fsS -X POST http://localhost:8080/orders/ORD-SYN-001/payment \
  -H 'Content-Type: application/json' -d '{"paymentToken":"PAY-SYN-001"}' | jq .
curl -fsS http://localhost:8080/orders/ORD-SYN-001 | jq '.status'   # PAID

curl -fsS -X POST http://localhost:8080/orders/ORD-SYN-001/shipment \
  -H 'Content-Type: application/json' -d '{"carrier":"SYNTHETIC-CARRIER"}' | jq .
curl -fsS http://localhost:8080/orders/ORD-SYN-001 | jq '.status'   # SHIPPED
```

Talking point: **same order ID, same endpoint, a different — correct — answer every time.** Now
reset it back to zero in one call, live, in front of the room:

```bash
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/reset" | jq '.current_state'   # NOT_CREATED
```

The reset response's own `current_state` is the proof — this example scenario has no explicit
"not found" handler wired up for `NOT_CREATED`, so don't rely on a raw `GET` against the order ID
here; it'll fall through to a generic contract-derived stub rather than 404, which reads as broken
on screen rather than "reset."

> "No more waiting on someone to reset the shared sandbox. This is the moment that usually gets
> a reaction from QA in the room."

## 6. Fault injection on purpose (5 min)

**Activating a profile alone only updates the compiled bundle — it has no effect on the running
service until you redeploy.** Redeploy with `reset_existing: true` right after, not `false`:
plain redeploy can leave an old, non-profiled copy of the scenario mapping alongside the new
profiled one, and WireMock's match between the two isn't guaranteed, which makes the delay/failure
show up inconsistently. `reset_existing: true` clears every mapping on the WireMock instance first,
so only do this against a demo instance with one simulation on it — it is not scoped to
`$SIMULATION_ID`.

```bash
curl -fsS -X PUT "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/profiles/slow" \
  -H 'Content-Type: application/json' -d '{"fixed_delay_ms": 3000, "failure_status": 503}' | jq .
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/deploy" \
  -H 'Content-Type: application/json' -d '{"reset_existing": true}' | jq .
time curl -fsS http://localhost:8080/orders/ORD-SYN-001   # ~3s, deterministic delay

curl -fsS -X PUT "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/profiles/unavailable" \
  -H 'Content-Type: application/json' -d '{"fixed_delay_ms": 0, "failure_status": 503}' | jq .
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/deploy" \
  -H 'Content-Type: application/json' -d '{"reset_existing": true}' | jq .
curl -i http://localhost:8080/orders/ORD-SYN-001 | head -1   # 503

curl -fsS -X PUT "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/profiles/normal" \
  -H 'Content-Type: application/json' -d '{}' | jq .
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/deploy" \
  -H 'Content-Type: application/json' -d '{"reset_existing": true}' | jq .
```

Console equivalent: **"3. Behavior" → pick `slow`/`unavailable`/`intermittent` → Activate profile,
then go back to "2. Runtime bundle" → Deploy.** The console's Deploy button always sends
`reset_existing: false`, so it carries the same inconsistency risk described above — rehearse this
exact step before presenting it live, and don't inspect the order immediately if it doesn't show
the expected delay/failure on the first click; redeploying once more resolves it.
`intermittent` is the one worth calling out — it fails *some* of the time, which is exactly the
flaky-payment-gateway bug that's hardest to reproduce against a real dependency.

## 7. Validation evidence — proof, not vibes (5 min)

```bash
curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validation/plan" \
  -H 'Content-Type: application/json' \
  -d '{"max_dataset_cases": 3, "include_boundary_cases": true, "include_negative_cases": true, "include_pairwise_cases": true}' |
  jq '.summary'

curl -fsS -X POST "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validate" \
  -H 'Content-Type: application/json' \
  -d '{"max_dataset_cases": 3, "reset_runtime_state": true, "include_boundary_cases": true, "include_negative_cases": true, "include_pairwise_cases": true}' |
  jq '.summary'

curl -fsS "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/reports/latest" |
  jq '{operation_coverage, scenario_coverage, state_coverage, transition_coverage, boundary_coverage, negative_coverage}'
curl -fsS "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/reports/latest/html" \
  -o /tmp/evidence.html && open /tmp/evidence.html   # or xdg-open / start
```

Talking point: the report separates **operation, scenario, boundary, negative, and pairwise**
coverage. A green `200 OK` on the happy path doesn't tell you whether the negative and boundary
cases were ever exercised — this does.

## 8. Portability, audit, GitOps (4 min)

```bash
curl -fsS "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/export/bundle" \
  -o /tmp/order-lifecycle.simuloom.zip
unzip -l /tmp/order-lifecycle.simuloom.zip
```

Talking points, don't need to run all of these live:
- That zip re-imports on any teammate's machine or in CI — no re-authoring the simulation.
- Every mutating call is audit-logged (`audit://domain/events` MCP resource, or
  `docs/release-runbook.md`-style signing key) — who did what, when, and whether it was allowed.
- `export_gitops_snapshot` (MCP tool) or the equivalent REST export puts scenario definitions
  under normal git version control and code review, same as application code.

## 9. AI Copilot with a hard trust boundary (4-5 min)

Console: **05 AI Copilot → select the simulation → New conversation.**

Ask something grounded in the real simulation, e.g. *"Why might the payment scenario fail during
shipment?"* — the answer cites the actual validation summary and failed-case evidence, not a
generic guess.

Then ask it to *do* something, e.g. *"Turn on the slow profile so we can test our timeout
handling."* It proposes the action as a card with **Approve / Reject** — click Approve yourself,
on screen.

> "That's the whole trust model in one click: the model can read everything and propose anything
> allowlisted, but nothing executes until a human — same role checks as REST — explicitly
> approves it. It's also local-only via Ollama by default; nothing leaves the machine."

REST equivalent, if you'd rather show the API:

```bash
THREAD_ID=$(curl -fsS -X POST http://localhost:8000/api/v1/ai/chat/threads \
  -H 'Content-Type: application/json' \
  -d "{\"simulation_id\": \"$SIMULATION_ID\", \"title\": \"Demo\"}" | jq -r '.id')
curl -fsS -X POST "http://localhost:8000/api/v1/ai/chat/threads/$THREAD_ID/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content": "Why might the payment scenario fail during shipment?"}' | jq .
```

## 10. MCP: the same platform, driven by an AI agent (5 min)

```bash
curl -s http://localhost:8000/mcp -H 'Accept: text/event-stream' -i | head -5   # confirm it's live
```

Talking point: `src/simuloom/mcp/server.py` exposes **44 tools** — everything you just clicked or
curled (`create_simulation`, `configure_scenario`, `deploy_scenario`, `run_validation`,
`activate_profile`, `export_simulation`, team-workspace administration, GitOps snapshot export,
and more) — plus **17 read-only resources** (`simulation://{id}/manifest`,
`evidence://{id}/latest`, `audit://domain/events`, `runtime://current/capabilities`, ...), all
under the same role checks as REST.

If Claude Code, Claude Desktop, or another MCP client is already configured against this server,
this is the strongest closing beat: ask it live, in the room, *"list the simulations in SimuLoom
and run validation on the order-lifecycle one"* and let people watch the tool calls happen against
the exact state you've been driving by hand all demo.

## 11. Rapid-fire, if time allows (2-3 min)

- **RBAC**: viewer/operator/admin roles, same boundary on REST, console, and MCP.
- **Revisions, releases, approval gates**: promote an immutable revision, require review before
  deploy, roll back a release.
- **Edge-case and pairwise generation**: automatic boundary/negative values and pairwise parameter
  combinations, not just the happy path.
- **Native runtime**: `SIMULOOM_RUNTIME=native` drops the WireMock dependency entirely — SQLite or
  in-memory, same contract behavior.
- **This repo's own CI** (`.github/workflows/`) uses SimuLoom's WireMock integration pattern to
  test itself — dogfooding, not just a demo app.

## 12. Close (3 min)

> "One governed simulation. Three identical surfaces — console, REST, MCP. Evidence instead of
> vibes. AI that can propose but never unilaterally act. Try it: `pip install simuloom-mcp`,
> `docker pull ghcr.io/anzar-ahsan-commits/simuloom-mcp`, or the five-minute guide in the repo."

## Cleanup

```bash
docker compose down            # keeps the workspace volume
docker compose down --volumes  # wipes it — only if you mean to
```

## If something breaks live

- **Nothing responds**: `docker compose logs`, then `docker compose restart simuloom`.
- **Deploy/compile fails**: you likely skipped a step out of order — re-run §4 before §5.
- **Copilot won't answer**: confirm `SIMULOOM_AI_ENABLED=true` and `ollama list` includes the
  configured model *before* the demo starts (see [troubleshooting](troubleshooting.md#ollama-connectivity-for-the-optional-ai-copilot)).
  Have the narrated fallback ready — don't debug it live.
- **Full reset**: `docker compose down --volumes && docker compose up --build -d`, then repeat
  from §3 — total downtime under a minute.
