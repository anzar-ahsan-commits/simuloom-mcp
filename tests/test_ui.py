import json

from fastapi.testclient import TestClient

from simuloom.main import app, create_app
from simuloom.security import AccessController


def test_console_and_assets_are_bundled_with_security_headers() -> None:
    client = TestClient(app)
    try:
        root = client.get("/", follow_redirects=False)
        console = client.get("/ui")
        script = client.get("/ui/assets/app.js")
        designer = client.get("/ui/assets/designer.js")
        styles = client.get("/ui/assets/styles.css")
    finally:
        client.close()

    assert root.status_code == 307
    assert root.headers["location"] == "/ui"
    assert console.status_code == 200
    assert "SimuLoom Console" in console.text
    assert "default-src 'self'" in console.headers["content-security-policy"]
    assert console.headers["x-frame-options"] == "DENY"
    assert script.status_code == 200
    assert "sessionStorage" in script.text
    assert designer.status_code == 200
    assert "scenario-graph" in designer.text
    assert "createElementNS" in designer.text
    assert 'headers["If-Match"]' in designer.text
    assert "scenario changed on the server" in designer.text
    assert "/history" in designer.text
    assert "beforeunload" in designer.text
    assert "compareDesignerRevisions" in designer.text
    assert "showScenarioReleases" in designer.text
    assert "rollbackDesignerRelease" in designer.text
    assert "showScenarioReviews" in designer.text
    assert "runDesignerAutomation" in designer.text
    assert "innerHTML = definition" not in designer.text
    assert styles.status_code == 200
    assert "--accent" in styles.text
    assert "content-security-policy" in script.headers


def test_console_shell_is_public_but_data_api_remains_authenticated() -> None:
    keys = {
        "viewer-console-key": {"subject": "console-viewer", "role": "viewer"},
    }
    protected = create_app(AccessController(True, json.dumps(keys)))
    client = TestClient(protected)
    try:
        console = client.get("/ui")
        denied = client.get("/api/v1/simulations")
        allowed = client.get("/api/v1/simulations", headers={"X-API-Key": "viewer-console-key"})
        session = client.get("/api/v1/session", headers={"X-API-Key": "viewer-console-key"})
    finally:
        client.close()

    assert console.status_code == 200
    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert session.json()["role"] == "viewer"
    assert session.json()["authentication_enabled"] is True
