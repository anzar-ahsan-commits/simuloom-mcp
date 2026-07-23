# Pairwise pricing checkout

This fictional checkout API contains several interacting factors: region, sales channel,
tier, quantity, expedited delivery, and an optional coupon. SimuLoom covers every two-factor
value interaction without executing the full Cartesian product.

Start the stack and create the simulation:

```bash
docker compose up --build -d

uv run python - <<'PY'
import json
from pathlib import Path
import yaml

contract = yaml.safe_load(Path("examples/pricing-checkout/openapi.yaml").read_text())
Path("/tmp/simuloom-pairwise.json").write_text(
    json.dumps({"name": "Pairwise Checkout Demo", "contract": contract})
)
PY

SIMULATION_ID=$(
  curl -fsS -X POST http://localhost:8000/api/v1/simulations \
    -H 'Content-Type: application/json' \
    --data-binary @/tmp/simuloom-pairwise.json |
  uv run python -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/compile"

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/deploy" \
  -H 'Content-Type: application/json' \
  -d '{"reset_existing":false}'
```

Preview and execute the pairwise suite:

```bash
curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validation/plan" \
  -H 'Content-Type: application/json' \
  -d '{
    "max_dataset_cases": 3,
    "include_pairwise_cases": true,
    "max_pairwise_cases_per_operation": 25
  }'

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validate" \
  -H 'Content-Type: application/json' \
  -d '{
    "max_dataset_cases": 3,
    "reset_runtime_state": true,
    "include_pairwise_cases": true,
    "max_pairwise_cases_per_operation": 25
  }'
```

The report's `pairwise_coverage` is 100% when the configured cap is sufficient. If a lower cap
prevents full two-way coverage, the report fails and shows the incomplete percentage.
