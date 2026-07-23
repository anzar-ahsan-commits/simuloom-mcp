# Contributing to SimuLoom

Thank you for helping improve deterministic service virtualization. Contributions should preserve
the core trust boundary: approved OpenAPI contracts remain authoritative, generated data remains
synthetic, and AI output never receives implicit mutation authority.

## Development setup

```bash
git clone https://github.com/anzar-ahsan-commits/simuloom-mcp.git
cd simuloom-mcp
uv sync --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

Run the complete local stack with `docker compose up --build -d`. WireMock is available on port
8080 and the SimuLoom console on port 8000. Ollama is optional; AI tests use deterministic mocked
transports unless explicitly described as live tests.

## Pull requests

- Open an issue before large architectural changes.
- Keep changes focused and avoid unrelated refactoring.
- Add tests for new behavior and regression tests for fixes.
- Update REST, MCP, security, and example documentation when their contracts change.
- Never include customer contracts, production payloads, credentials, or personal data.
- Use conventional, imperative commit subjects such as `fix: prevent duplicate approval`.

Every pull request must pass tests, Ruff lint and formatting, package build, and the WireMock
integration suite. Security-sensitive changes should explain their threat model and failure modes.

## Reporting security issues

Do not open a public issue for a vulnerability. Follow [SECURITY.md](SECURITY.md) and use GitHub
private vulnerability reporting.
