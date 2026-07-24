# Troubleshooting the five-minute guide

Fixes for the problems that most often interrupt a first run of the
[five-minute order-lifecycle walkthrough](launch.md). If something here does not resolve your
issue, tell us where it stalled using the
[onboarding feedback template](../.github/ISSUE_TEMPLATE/onboarding_feedback.yml).

## Ports 8000 or 8080 are already in use

SimuLoom listens on `8000` and WireMock on `8080`. If `docker compose up` fails or the console
does not load:

```bash
# Find what already owns the port (Linux/macOS)
lsof -i :8000
lsof -i :8080

# Windows PowerShell
Get-NetTCPConnection -LocalPort 8000,8080
```

Stop the conflicting process, or remap the published port in `docker-compose.yml` (for example
`"8001:8000"`) and use the new port for every `curl`/browser step below.

## Docker is not ready yet

`docker compose up --build -d` returns immediately; the containers still need to build and pass
their health checks. Symptoms: `curl: (7) Failed to connect`, or the console shows a network
error.

```bash
docker compose ps                 # both services should show "healthy" or "running"
docker compose logs simuloom      # look for a stack trace instead of a clean startup banner
docker compose logs wiremock      # confirm WireMock's admin API accepted the port
```

Re-run the readiness check until it returns `"status": "ready"`:

```bash
until curl --fail --silent http://localhost:8000/api/v1/readyz; do sleep 1; done
```

If Docker Desktop itself is still starting, wait for its tray icon to show "running" before
retrying `docker compose up`.

## Workspace state did not persist across a restart

SimuLoom stores simulations, scenarios, and audit history under the `simuloom-workspace` named
volume (see `docker-compose.yml`). Restarting the container preserves that volume; only
`docker compose down --volumes` discards it deliberately.

```bash
docker volume ls | grep simuloom-workspace       # confirm the volume exists
docker compose down                              # keeps the volume
docker compose down --volumes                    # discards it — only when you mean to
```

Running SimuLoom directly with `uv run uvicorn ...` instead of Docker uses `SIMULOOM_WORKSPACE`
(defaults to `./workspace` in the repository) on your local filesystem instead of a Docker
volume — check that path if state looks empty after a restart in that mode.

## Ollama connectivity for the optional AI Copilot

The AI Copilot (`SIMULOOM_AI_ENABLED=true`) is optional, local-only, and off by default. If it
reports it cannot reach the model:

- Confirm Ollama is running on the host: `curl http://localhost:11434/api/version`.
- From inside the Docker container, the host is `host.docker.internal`
  (`SIMULOOM_AI_BASE_URL=http://host.docker.internal:11434` by default in `docker-compose.yml`).
  On Linux hosts without that DNS alias, add
  `extra_hosts: ["host.docker.internal:host-gateway"]` to the `simuloom` service, or point
  `SIMULOOM_AI_BASE_URL` at the host's real IP.
- Confirm the configured model is pulled: `ollama list` should include `SIMULOOM_AI_MODEL`
  (`qwen3:8b` by default). Pull it with `ollama pull qwen3:8b` if missing.
- The console's readiness panel reports the AI connectivity state and latency directly — check
  it before assuming a network problem.

## REST or MCP calls return 401 or 403

Authentication is disabled by default for local evaluation, so this only applies once
`SIMULOOM_AUTH_ENABLED=true` is set (see [Authentication and roles](../README.md#authentication-and-roles)).

- `401` means no key was recognized: send `Authorization: Bearer <key>` or `X-API-Key: <key>`,
  and confirm the key matches one configured in `SIMULOOM_API_KEYS` exactly (no surrounding
  quotes or whitespace).
- `403` means the key authenticated but its role is too low for the operation: `viewer` can read
  only; mutating calls need `operator` or `admin`.
- The same headers gate `/mcp`, not only `/api/v1/*`.

## WireMock mappings are not there yet

Compiling and deploying a simulation pushes stub mappings into WireMock. If a request to the
mocked API returns WireMock's default 404 page instead of your simulated response, confirm the
deploy step actually ran and that WireMock finished starting first:

```bash
curl --fail --silent http://localhost:8080/__admin/mappings
```

An empty `"mappings": []` array means SimuLoom has not deployed anything yet — revisit the
compile/deploy step in the [order lifecycle example](../examples/order-lifecycle/README.md).

## Still stuck

Open an [onboarding feedback issue](../.github/ISSUE_TEMPLATE/onboarding_feedback.yml) with the
step you were on, what you expected, and how long you had been trying — that is exactly the
signal that helps us shorten the guide for the next person.
