# Order lifecycle scenario

This example contains only fictional identifiers and payloads. Start SimuLoom and WireMock:

```bash
docker compose up --build -d
```

To run the same scenario without using WireMock, select the native adapter:

```bash
SIMULOOM_RUNTIME=native docker compose up --build -d
curl -fsS http://localhost:8000/api/v1/runtime
```

Create JSON request files from the checked-in YAML examples:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
import yaml

contract = yaml.safe_load(Path("examples/order-lifecycle/openapi.yaml").read_text())
scenario = yaml.safe_load(Path("examples/order-lifecycle/scenario.yaml").read_text())
Path("/tmp/simuloom-create.json").write_text(
    json.dumps({"name": "Order Lifecycle Demo", "contract": contract})
)
Path("/tmp/simuloom-scenario.json").write_text(json.dumps(scenario))
PY
```

Create the simulation and configure, compile, and deploy its scenario:

```bash
SIMULATION_ID=$(
  curl -fsS -X POST http://localhost:8000/api/v1/simulations \
    -H 'Content-Type: application/json' \
    --data-binary @/tmp/simuloom-create.json |
  uv run python -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)

curl -fsS -X PUT \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle" \
  -H 'Content-Type: application/json' \
  --data-binary @/tmp/simuloom-scenario.json

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/compile"

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/deploy"
```

Choose the virtual-service base. Use the first line for WireMock (the default), or the second
for the native adapter, then exercise every lifecycle step:

```bash
SERVICE_BASE=http://localhost:8080
# SERVICE_BASE="http://localhost:8000/runtime/$SIMULATION_ID"

curl -fsS -X POST "$SERVICE_BASE/orders" \
  -H 'Content-Type: application/json' \
  -d '{"itemId":"ITEM-SYN-001","quantity":1}'

curl -fsS "$SERVICE_BASE/orders/ORD-SYN-001"

curl -fsS -X POST "$SERVICE_BASE/orders/ORD-SYN-001/payment" \
  -H 'Content-Type: application/json' \
  -d '{"paymentToken":"PAY-SYN-001"}'

curl -fsS "$SERVICE_BASE/orders/ORD-SYN-001"

curl -fsS -X POST "$SERVICE_BASE/orders/ORD-SYN-001/shipment" \
  -H 'Content-Type: application/json' \
  -d '{"carrier":"SYNTHETIC-CARRIER"}'

curl -fsS "$SERVICE_BASE/orders/ORD-SYN-001"
```

Inspect and reset the scenario, then create the order again:

```bash
curl -fsS \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/state"

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/reset"

curl -fsS -X POST "$SERVICE_BASE/orders" \
  -H 'Content-Type: application/json' \
  -d '{"itemId":"ITEM-SYN-001","quantity":1}'
```

Generate and execute evidence for every reachable state and transition:

```bash
curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validation/plan" \
  -H 'Content-Type: application/json' \
  -d '{"max_dataset_cases":3}'

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validate" \
  -H 'Content-Type: application/json' \
  -d '{"max_dataset_cases":3,"reset_runtime_state":true}'

curl -fsS \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/reports/latest"

curl -fsS \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/reports/latest/html" \
  -o /tmp/simuloom-order-evidence.html
```

The report must show 100% state and transition coverage for this example. Scenario cases are
independent replays, so validation may leave the selected runtime in the final state of the last replay;
use the scenario reset endpoint before another manual walkthrough.

When authentication is enabled, add `Authorization: Bearer $SIMULOOM_KEY` or
`X-API-Key: $SIMULOOM_KEY` to SimuLoom API requests. Virtual-service requests are outside
control-plane authentication and remain subject to your deployment's network controls.
