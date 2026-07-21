# Order lifecycle scenario

This example contains only fictional identifiers and payloads. Start SimuLoom and WireMock:

```bash
docker compose up --build -d
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

Exercise every lifecycle step against WireMock:

```bash
curl -fsS -X POST http://localhost:8080/orders \
  -H 'Content-Type: application/json' \
  -d '{"itemId":"ITEM-SYN-001","quantity":1}'

curl -fsS http://localhost:8080/orders/ORD-SYN-001

curl -fsS -X POST http://localhost:8080/orders/ORD-SYN-001/payment \
  -H 'Content-Type: application/json' \
  -d '{"paymentToken":"PAY-SYN-001"}'

curl -fsS http://localhost:8080/orders/ORD-SYN-001

curl -fsS -X POST http://localhost:8080/orders/ORD-SYN-001/shipment \
  -H 'Content-Type: application/json' \
  -d '{"carrier":"SYNTHETIC-CARRIER"}'

curl -fsS http://localhost:8080/orders/ORD-SYN-001
```

Inspect and reset the scenario, then create the order again:

```bash
curl -fsS \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/state"

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/scenarios/order-lifecycle/reset"

curl -fsS -X POST http://localhost:8080/orders \
  -H 'Content-Type: application/json' \
  -d '{"itemId":"ITEM-SYN-001","quantity":1}'
```

When authentication is enabled, add `Authorization: Bearer $SIMULOOM_KEY` or
`X-API-Key: $SIMULOOM_KEY` to SimuLoom API requests. Direct WireMock example requests
remain subject to the network controls around your WireMock deployment.
