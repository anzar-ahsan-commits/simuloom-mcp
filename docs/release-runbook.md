# Release runbook

How SimuLoom releases are built, and how to recover if one goes wrong. See also
[release.yml](../.github/workflows/release.yml),
[publish-pypi.yml](../.github/workflows/publish-pypi.yml), and
[release-dry-run.yml](../.github/workflows/release-dry-run.yml).

## How a release ships

1. `pyproject.toml`'s `version`, `src/simuloom/__init__.py`'s `__version__`, and the newest
   `CHANGELOG.md` entry must all agree. `tests/test_release_metadata.py` enforces this in CI
   before a tag is ever pushed.
2. Pushing a tag matching `v*` triggers `release.yml`, which builds the wheel/sdist, verifies the
   tag matches `simuloom.__version__` (failing the job — and publishing nothing — on mismatch),
   attests provenance, creates the GitHub Release, and builds/pushes the `ghcr.io` container image
   with matching semver tags.
3. `publish-pypi.yml` runs after `release.yml` succeeds (or via manual dispatch with an existing
   tag) and publishes to PyPI using Trusted Publishing (OIDC — no long-lived API token).
4. `verify-public-artifacts.yml` (see [issue #28](https://github.com/anzar-ahsan-commits/simuloom-mcp/issues/28))
   then continuously confirms the published wheel and image actually work from a clean
   environment.

Before pushing a real tag, you can run the same build-and-verify steps with nothing published by
triggering **Release dry run** (`workflow_dispatch` on `release-dry-run.yml`, or it runs
automatically on any PR touching `Dockerfile`, `pyproject.toml`, or the release workflows).

## Tag/version mismatch

`release.yml`'s "Verify tag matches package version" step fails the job (before any artifact is
attested, released, or pushed) if the pushed tag doesn't equal `v${simuloom.__version__}`.
Recovery:

```bash
# Delete the bad tag locally and on the remote — nothing was published, so this is safe.
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
```

Fix the mismatch (bump `pyproject.toml`/`__init__.py`/`CHANGELOG.md` together, or re-tag with the
correct version), then push the corrected tag.

## GitHub Release went out wrong

Nothing downstream (PyPI, GHCR) depends on the GitHub Release object itself, so it's safe to
replace:

```bash
gh release delete vX.Y.Z --yes        # keeps the git tag; add --cleanup-tag to remove that too
# fix the problem, then re-run release.yml by re-pushing the tag if you removed it,
# or re-run the workflow manually against the existing tag.
```

## GHCR image went out wrong

Container images are content-addressed; a bad tag doesn't invalidate a previously-good one.

- Point consumers back at a known-good tag or digest (`ghcr.io/anzar-ahsan-commits/simuloom-mcp@sha256:...`)
  while you investigate.
- Delete the bad version from **Packages → simuloom-mcp → Versions** in the GitHub UI, or via the
  API: `gh api -X DELETE /orgs/anzar-ahsan-commits/packages/container/simuloom-mcp/versions/<id>`.
- Publish a corrected patch release rather than reusing the same tag — GHCR tags are mutable, but
  re-pushing a tag that's already been pulled leaves stale copies in the wild.

## PyPI publish went out wrong

**PyPI files are immutable — a bad release cannot be deleted or overwritten**, only yanked:

```bash
python -m pip index versions simuloom-mcp    # confirm what's actually live
```

1. Open the release on [pypi.org/project/simuloom-mcp](https://pypi.org/project/simuloom-mcp/#history)
   and select **Yank release**. Yanking hides the version from `pip install simuloom-mcp` (default
   resolution skips yanked versions) without deleting it, so anyone already pinned to that exact
   version (`==X.Y.Z`) is unaffected and can still reproduce their build.
2. Bump `pyproject.toml`/`__init__.py`/`CHANGELOG.md` to the next patch version with the fix, and
   ship a normal release through the pipeline above. There is no way to "retry" the same version
   number on PyPI.
3. If credentials were ever a concern: publishing uses OIDC Trusted Publishing
   (`permissions: id-token: write`, no stored PyPI token to rotate), so a compromised workflow run
   cannot leak a long-lived secret — only the `pypi` GitHub Environment's configuration controls
   who can trigger it.
