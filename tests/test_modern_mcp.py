import json
from pathlib import Path

from test_scenarios import contract

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.platform_store import PlatformStore
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.mcp import server as mcp_server
from simuloom.security import Principal, Role, _current_principal


def test_modern_mcp_workspace_tools_and_resource(tmp_path: Path, monkeypatch) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    monkeypatch.setattr(mcp_server, "platform_store", store)
    token = _current_principal.set(Principal("platform-owner", Role.ADMIN, None))
    try:
        workspace = mcp_server.create_team_workspace("MCP Platform")
        member = mcp_server.set_team_workspace_member(workspace["id"], "qa-engineer", "operator")
        listed = mcp_server.list_team_workspaces()
        overview = json.loads(mcp_server.team_workspace_overview(workspace["id"]))
    finally:
        _current_principal.reset(token)

    assert member["role"] == "operator"
    assert [item["id"] for item in listed] == [workspace["id"]]
    assert {item["subject"] for item in overview["members"]} == {
        "platform-owner",
        "qa-engineer",
    }
    assert overview["secrets"] == []


def test_mcp_ai_conversation_resource_is_owner_scoped(tmp_path: Path, monkeypatch) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    service = SimulationService(
        WorkspaceRepository(tmp_path / "workspace"), WireMockClient("http://wiremock.invalid")
    )
    simulation = service.create("MCP AI simulation", contract())
    monkeypatch.setattr(mcp_server, "platform_store", store)
    monkeypatch.setattr(mcp_server, "service", service)
    token = _current_principal.set(Principal("copilot-owner", Role.VIEWER, None))
    try:
        thread = mcp_server.create_ai_conversation(simulation.id, "MCP assistant")
        resource = json.loads(mcp_server.ai_chat_conversation_resource(thread["id"]))
    finally:
        _current_principal.reset(token)

    assert resource["simulation_id"] == simulation.id
    assert resource["owner"] == "copilot-owner"
    assert resource["messages"] == []
