# Public Launch Runbook

This runbook separates repository changes from owner-only settings that cannot be safely automated
from a contributor branch.

## Automated by the repository

- Tests, lint, formatting, build, CLI, and WireMock integration in CI.
- CodeQL scanning on pull requests, main, and a weekly schedule.
- Weekly Python, Docker, and GitHub Actions dependency updates.
- Tag-driven Python distribution and GHCR image builds.
- Provenance attestations for distributions and container images.
- OIDC-based PyPI publication after a successful release workflow, with a manual recovery trigger
  and no long-lived package token.
- Structured contribution, support, issue, pull request, security, and governance guidance.

## Owner setup before the first public release

1. Enable GitHub Discussions.
2. Enable private vulnerability reporting.
3. Enable the dependency graph, Dependabot alerts, and Dependabot security updates.
4. Protect `main`: require pull requests, CI and CodeQL checks, resolved conversations, and no
   force pushes or deletions.
5. Create a GitHub environment named `pypi` with required reviewer protection.
6. On PyPI, create a pending Trusted Publisher for:
   - owner: `anzar-ahsan-commits`
   - repository: `simuloom-mcp`
   - workflow: `publish-pypi.yml`
   - environment: `pypi`
7. After the first container publication, set the GHCR package visibility to public and confirm it
   is linked to this repository.
8. Replace any placeholder social/contact details and decide who handles conduct and security
   reports during maintainer absence.
9. Self-assess the OpenSSF Best Practices baseline and display a badge only after it is awarded.

## Release candidate gate

- Freeze the milestone scope and update `CHANGELOG.md`.
- Confirm package, API, UI, and deployment versions match the proposed tag.
- Run the complete local and live-runtime checks in `docs/technical-guide.md`.
- Test a clean installation from the built wheel.
- Test the GHCR image without a bind-mounted source tree.
- Exercise the order lifecycle and one real Ollama conversation.
- Review generated OpenAPI and MCP tool lists for accidental breaking changes.
- Verify no secret, production payload, workspace database, or generated report is tracked.
- Review container vulnerabilities and all open Dependabot/CodeQL alerts.
- Create an annotated tag such as `v0.42.0` only from a reviewed main commit.

## Launch messaging

Describe SimuLoom as a **public beta**, not a production SLA-backed platform. Lead with the real
problem: deterministic virtual services and evidence from approved OpenAPI contracts. AI is an
optional local assistant, not the source of truth.

The launch page should show:

- a five-minute Docker quick start;
- the order-lifecycle demonstration;
- a screenshot or short recording of the visual scenario designer and Copilot;
- REST and MCP examples;
- an explicit synthetic-data and security statement;
- current limitations and the roadmap.

## Post-launch operations

- Triage issues and discussions at a predictable cadence.
- Publish security advisories and patched releases promptly.
- Track installation failures, time-to-first-simulation, validation success, and documentation
  gaps without adding invasive product analytics.
- Maintain a compatibility table for Python, WireMock, Ollama, and runtime adapters.
- Promote from public beta only after OIDC, multi-replica storage, retention controls, and recovery
  exercises are complete.
