from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from simuloom.main import app


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
