from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from simuloom.main import app


def test_public_release_automation_and_community_files_are_present() -> None:
    workflow_paths = [
        Path(".github/workflows/ci.yml"),
        Path(".github/workflows/codeql.yml"),
        Path(".github/workflows/release.yml"),
        Path(".github/workflows/publish-pypi.yml"),
    ]

    for path in workflow_paths:
        assert isinstance(yaml.safe_load(path.read_text()), dict)

    for path in [
        Path("CONTRIBUTING.md"),
        Path("GOVERNANCE.md"),
        Path("SUPPORT.md"),
        Path("SECURITY.md"),
        Path("docs/public-launch.md"),
        Path("docs/technical-guide.md"),
    ]:
        assert path.read_text().strip()


def test_kubernetes_manifest_uses_non_root_security_and_probes() -> None:
    resources = list(yaml.safe_load_all(Path("deploy/kubernetes.yaml").read_text()))
    deployment = next(
        item
        for item in resources
        if item["kind"] == "Deployment" and item["metadata"]["name"] == "simuloom"
    )
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert deployment["spec"]["replicas"] == 1
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["readinessProbe"]["httpGet"]["path"] == "/api/v1/readyz"
    assert container["livenessProbe"]["httpGet"]["path"] == "/api/v1/health"


def test_public_readyz_is_usable_by_orchestrators() -> None:
    client = TestClient(app)
    try:
        response = client.get("/api/v1/readyz")
    finally:
        client.close()

    assert response.status_code in {200, 503}
    assert response.json()["status"] in {"ready", "not-ready"}


def test_container_entrypoint_is_scoped_and_drops_privileges() -> None:
    source = Path("src/simuloom/container_entrypoint.py").read_text()

    assert 'Path("/app/workspace")' in source
    assert "os.setgid(APP_GID)" in source
    assert "os.setuid(APP_UID)" in source
    assert "os.execvp" in source


def test_container_image_runs_as_the_unprivileged_application_user() -> None:
    dockerfile = Path("Dockerfile").read_text()

    assert "USER 10001:10001" in dockerfile
