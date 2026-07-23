# Meet SimuLoom: deterministic virtual services from OpenAPI

SimuLoom is an open-source control plane for teams that need realistic APIs before every real
dependency is available, affordable, or safe to call. It turns an approved OpenAPI contract into
synthetic data, deterministic virtual-service behavior, stateful scenarios, and validation
evidence. REST, MCP, and the operator console use the same application services, so automation
and humans see the same source of truth.

SimuLoom `v0.42.0` is a public beta. It is useful for local development, integration testing,
demos, CI experiments, and learning. It does not claim a production SLA or replace testing
against the real provider.

## Five-minute Docker walkthrough

Prerequisites: Git, Docker, and Docker Compose.

```bash
git clone https://github.com/anzar-ahsan-commits/simuloom-mcp.git
cd simuloom-mcp
git checkout v0.42.0
docker compose up --build -d

curl --fail http://localhost:8000/api/v1/health
curl --fail http://localhost:8000/api/v1/readyz
```

Open:

- operator console: <http://localhost:8000/ui>
- interactive REST documentation: <http://localhost:8000/docs>
- MCP endpoint: <http://localhost:8000/mcp>
- WireMock: <http://localhost:8080>

Follow the copy-pasteable [order lifecycle](../examples/order-lifecycle/README.md) to create,
inspect, pay, and ship a synthetic order. The scenario moves deterministically through
`NOT_CREATED → PENDING → PAID → SHIPPED`, then resets to its initial state.

Stop the local stack when finished:

```bash
docker compose down
```

The named workspace volume is retained. Use `docker compose down --volumes` only when you
explicitly want to discard local SimuLoom state.

## Install the Python package

The signed public package is available from PyPI:

```bash
python -m pip install "simuloom-mcp==0.42.0"
python -c "import importlib.metadata as m; print(m.version('simuloom-mcp'))"
simuloom-gitops --help
```

The public container is:

```text
ghcr.io/anzar-ahsan-commits/simuloom-mcp:0.42.0
```

## Why teams use it

- Frontend and integration teams can work before an upstream service is ready.
- QA teams can replay deterministic happy paths, failures, boundaries, and state transitions.
- Platform teams can validate approved contracts through REST, MCP, GitOps snapshots, and CI.
- Demo environments can avoid production credentials and customer data.
- Local AI can explain evidence and draft proposals without silently deploying changes.

## Trust and safety model

- OpenAPI and saved scenario definitions—not AI output—are authoritative.
- Checked-in examples use clearly fictional synthetic identifiers.
- AI is local and opt-in through Ollama; proposed mutations require explicit approval.
- Authentication, role checks, audit evidence, encrypted secrets, and outbound-host allowlists are
  available when moving beyond a single-developer evaluation.
- Published Python and container artifacts include provenance attestations.

## Current beta boundaries

The default durable stores are SQLite-based and intended for a single application instance.
WireMock owns live state when it is the selected runtime. Browser-level UI regression automation,
distributed coordination, hosted identity providers, and a production support SLA remain roadmap
work. See the [technical guide](technical-guide.md) for the full architecture and limitations.

## Join the project

- Ask questions and share use cases in
  [GitHub Discussions](https://github.com/anzar-ahsan-commits/simuloom-mcp/discussions).
- Report reproducible defects with the bug form in
  [GitHub Issues](https://github.com/anzar-ahsan-commits/simuloom-mcp/issues).
- Read [CONTRIBUTING.md](../CONTRIBUTING.md) before proposing a change.
- Report vulnerabilities through GitHub private vulnerability reporting, not a public issue.

The most useful early feedback is concrete: the contract you tried, the workflow you expected,
where onboarding slowed down, and which evidence would help you trust the result.
