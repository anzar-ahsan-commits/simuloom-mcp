# Constraint validation example

This fictional API documents a successful `201` response and a schema-valid `400` response.
SimuLoom can therefore generate both valid boundary requests and deterministic invalid requests.

Start the stack and create a simulation:

```bash
docker compose up --build -d

uv run python - <<'PY'
import json
from pathlib import Path
import yaml

contract = yaml.safe_load(Path("examples/constraint-validation/openapi.yaml").read_text())
Path("/tmp/simuloom-constraint.json").write_text(
    json.dumps({"name": "Constraint Validation Demo", "contract": contract})
)
PY

SIMULATION_ID=$(
  curl -fsS -X POST http://localhost:8000/api/v1/simulations \
    -H 'Content-Type: application/json' \
    --data-binary @/tmp/simuloom-constraint.json |
  uv run python -c 'import json,sys; print(json.load(sys.stdin)["id"])'
)

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/compile"

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/deploy" \
  -H 'Content-Type: application/json' \
  -d '{"reset_existing":false}'
```

Preview and run all generated edge cases:

```bash
curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validation/plan" \
  -H 'Content-Type: application/json' \
  -d '{
    "max_dataset_cases": 3,
    "include_boundary_cases": true,
    "include_negative_cases": true,
    "max_edge_cases_per_operation": 20
  }'

curl -fsS -X POST \
  "http://localhost:8000/api/v1/simulations/$SIMULATION_ID/validate" \
  -H 'Content-Type: application/json' \
  -d '{
    "max_dataset_cases": 3,
    "reset_runtime_state": true,
    "include_boundary_cases": true,
    "include_negative_cases": true,
    "max_edge_cases_per_operation": 20
  }'
```

The evidence response includes `boundary_coverage` and `negative_coverage`. Existing clients
that omit the new options continue to execute only the baseline, dataset, and scenario cases.
