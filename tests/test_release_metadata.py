import re
import tomllib
from pathlib import Path

import simuloom


def test_package_version_matches_pyproject():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    assert simuloom.__version__ == pyproject["project"]["version"]


def test_changelog_top_entry_matches_package_version():
    changelog = Path("CHANGELOG.md").read_text()
    match = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.MULTILINE)
    assert match is not None, "CHANGELOG.md has no '## X.Y.Z' entry"
    assert match.group(1) == simuloom.__version__, (
        "CHANGELOG.md's newest entry does not match simuloom.__version__; "
        "the release tag/version check in .github/workflows/release.yml will fail "
        "if pyproject.toml and the git tag are bumped without an accompanying entry"
    )
