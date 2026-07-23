import json

import httpx
import pytest
from test_scenarios import contract, definition_payload

from simuloom.core.ai_assistant import ScenarioAIAssistant


@pytest.mark.asyncio
async def test_local_ai_draft_uses_schema_and_contract_validation() -> None:
    captured: dict = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(definition_payload())}},
        )

    assistant = ScenarioAIAssistant(
        True,
        "http://ollama:11434",
        "qwen3:8b",
        httpx.MockTransport(respond),
    )

    definition = await assistant.draft(
        contract(), "Create, pay, and ship a synthetic order", "Order lifecycle"
    )

    assert definition.name == "Order lifecycle"
    assert captured["stream"] is False
    assert captured["options"] == {"temperature": 0, "seed": 1207}
    assert captured["format"]["title"] == "ScenarioDefinition"
    prompt = captured["messages"][1]["content"]
    assert "approved_operations" in prompt
    assert "operationId" not in prompt


@pytest.mark.asyncio
async def test_local_ai_is_disabled_by_default_and_cannot_mutate() -> None:
    assistant = ScenarioAIAssistant(False, "http://localhost:11434", "qwen3:8b")

    with pytest.raises(RuntimeError, match="disabled"):
        await assistant.draft(contract(), "Create a valid synthetic order lifecycle")


def test_local_ai_endpoint_rejects_credentials() -> None:
    with pytest.raises(ValueError, match="credentials"):
        ScenarioAIAssistant(True, "http://user:secret@localhost:11434", "model")
