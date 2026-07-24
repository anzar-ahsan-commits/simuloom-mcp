# Browser-level UI and accessibility testing

`e2e/` holds Playwright-driven tests against a real, already-running SimuLoom instance — the
operator console's navigation, simulation creation and lifecycle controls, scenario inspection,
Copilot conversation selection, keyboard operability, automated accessibility scans (axe-core),
and the two critical responsive breakpoints. It is deliberately separate from `tests/`
(`pytest`'s default `testpaths`), since it depends on Playwright's browser binaries and a running
server rather than being a pure unit/integration suite.

## Running locally

```bash
docker compose up --build -d
until curl --fail --silent http://localhost:8000/api/v1/readyz; do sleep 1; done

uv sync --extra e2e
uv run playwright install --with-deps chromium
uv run pytest e2e -v

docker compose down
```

Point at a different running instance with `SIMULOOM_E2E_BASE_URL` (defaults to
`http://localhost:8000`). Authentication must be disabled (`SIMULOOM_AUTH_ENABLED=false`, the
`docker-compose.yml` default) — every test assumes an admin session with no key required, matching
local evaluation.

Debug a failure interactively with Playwright's own tools:

```bash
uv run pytest e2e -v --headed --slowmo=250   # watch it run
uv run playwright show-trace test-results/*/trace.zip   # inspect a captured CI trace
```

## What's covered where

| File | Covers |
| --- | --- |
| `test_console_navigation.py` | Primary navigation, uploading a contract to create a simulation, selecting one, and the generate/compile/deploy lifecycle controls |
| `test_scenario_designer.py` | Scenario inspection: selecting a simulation and an already-deployed scenario, and the rendered state graph |
| `test_copilot.py` | Creating and switching between Copilot conversations (no AI/model dependency — thread management is plain CRUD) |
| `test_accessibility.py` | axe-core scans of each primary view; failures name the specific rule and CSS selector at fault |
| `test_keyboard_navigation.py` | Skip link, tab reachability, keyboard activation, visible focus indication, accessible names on icon-only controls |
| `test_responsive_layout.py` | Desktop sidebar layout vs. the ≤760px collapsed layout, and that navigation stays visible and labeled at both |

CI runs the whole suite in `.github/workflows/e2e.yml` against the real `docker compose` stack on
every push and pull request, uploading Playwright traces/screenshots/video as artifacts when a
test fails.

## Updating launch-guide screenshots

The screenshots embedded in [docs/launch.md](launch.md) (`docs/images/scenario-designer.png`,
`validation-evidence.png`, `ai-copilot.png`) are curated, not pixel-diffed against a stored
baseline — there is no automated visual-regression gate, which would be too flaky across
CI runners, fonts, and OS rendering to trust. Instead, `e2e/capture_screenshots.py` reproducibly
captures fresh candidates from a live instance:

```bash
docker compose up --build -d
until curl --fail --silent http://localhost:8000/api/v1/readyz; do sleep 1; done
uv run --extra e2e python e2e/capture_screenshots.py
```

This writes into `docs/images/e2e-captures/` (gitignored — never committed automatically). To
adopt a capture as a new launch-guide image:

1. Open it and compare against the current `docs/images/*.png` — check nothing sensitive or
   accidentally environment-specific (local hostnames, stray browser chrome) leaked in.
2. Crop/resize to match the existing images' aspect ratio if needed.
3. Replace the specific `docs/images/*.png` file and mention the change in your PR description so
   a reviewer looks at the new image, not just the diff stat.
