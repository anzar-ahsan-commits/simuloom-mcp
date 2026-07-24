# Compatibility

What is actually verified in CI, versus what is documented but not continuously tested. See the
[Verify public artifacts workflow](../.github/workflows/verify-public-artifacts.yml) for the
automation this table describes — it runs on a daily schedule, after every PyPI publish, and on
demand.

| Component | Supported | Continuously verified |
| --- | --- | --- |
| Python | `>=3.12` (`pyproject.toml`) | 3.12 and 3.13 — the published wheel is installed from PyPI into a clean environment and its console scripts are smoke-tested on both. |
| Container base | `python:3.12-slim` (`Dockerfile`) | The published GHCR image is pulled anonymously, checked for readiness/health, verified to run as its declared non-root UID (`10001`), and exercised through the full order-lifecycle example. |
| WireMock | Pinned at `3.13.2` (`docker-compose.yml`) | Covered by `tests/test_wiremock_integration.py` in CI against that pinned version. Not re-verified by the public-artifact workflow, which uses the dependency-free native runtime instead so it does not need a second container. |
| Ollama (optional local AI Copilot) | Any Ollama-compatible endpoint; documented default model `qwen3:8b` | Not run in CI — the Copilot is local-only and opt-in (`SIMULOOM_AI_ENABLED=false` by default), so there is no public endpoint to verify against. See [troubleshooting](troubleshooting.md#ollama-connectivity-for-the-optional-ai-copilot) if it can't reach your local model. |
| Docker / Docker Compose | Compose v2 (the `docker compose` subcommand, not standalone `docker-compose`) | Exercised indirectly by every CI run and the public-artifact workflow, both of which run on GitHub-hosted `ubuntu-latest` runners with a current Docker Engine. |

If you evaluate SimuLoom on a platform not listed here and hit a problem, please file it — see
[troubleshooting](troubleshooting.md) and the
[onboarding feedback template](../.github/ISSUE_TEMPLATE/onboarding_feedback.yml).
