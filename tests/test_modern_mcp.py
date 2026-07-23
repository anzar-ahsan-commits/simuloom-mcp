import json
from pathlib import Path

from simuloom.core.platform_store import PlatformStore
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
