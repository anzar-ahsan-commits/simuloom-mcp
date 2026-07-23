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
        copilot = client.get("/ui/assets/copilot.js")
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
    assert "draftScenarioWithAI" in designer.text
    assert "openWorkflowDialog" in designer.text
    assert "window.prompt" not in designer.text
    assert 'id="workflow-dialog"' in console.text
    assert 'id="workspaces-view"' in console.text
    assert 'data-view="copilot"' in console.text
    assert 'id="copilot-messages"' in console.text
    assert "Nothing executes until an operator approves it" in console.text
    assert "loadWorkspaceHubDetail" in script.text
    assert copilot.status_code == 200
    assert "decideCopilotAction" in copilot.text
    assert "/ai/chat/actions/" in copilot.text
    assert 'sessionStorage.getItem("simuloom-copilot-thread")' in copilot.text
    assert "rememberCopilotThread" in copilot.text
    assert 'api("/ai/settings")' in copilot.text
    assert "toggleCopilotAI" in copilot.text
    assert 'id="copilot-ai-toggle"' in console.text
    assert 'id="copilot-rename"' in console.text
    assert "archiveCopilotThread" in copilot.text
    assert "deleteCopilotThread" in copilot.text
    assert "Ollama unavailable" in copilot.text
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
