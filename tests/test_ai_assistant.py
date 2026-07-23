import json

import httpx
import pytest
from test_scenarios import contract, definition_payload

from simuloom.core.ai_assistant import ScenarioAIAssistant, _ollama_schema
from simuloom.models import AIChatCompletion, AIChatMessage


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


def test_ollama_schema_avoids_unsupported_large_repetition_grammar() -> None:
    schema = _ollama_schema(AIChatCompletion.model_json_schema())
    serialized = json.dumps(schema)

    assert '"maxLength"' not in serialized
    assert '"minLength"' not in serialized
    assert schema["title"] == "AIChatCompletion"


@pytest.mark.asyncio
async def test_local_ai_chat_is_grounded_and_returns_only_proposals() -> None:
    captured: dict = {}

    def respond(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = {
            "answer": "The simulation is ready to compile.",
            "actions": [
                {
                    "kind": "compile",
                    "arguments": {},
                    "summary": "Compile deterministic runtime mappings",
                    "risk": "medium",
                }
            ],
            "suggested_prompts": ["What should I validate next?"],
        }
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}})

    assistant = ScenarioAIAssistant(
        True, "http://ollama:11434", "qwen3:8b", httpx.MockTransport(respond)
    )
    history = [
        AIChatMessage(
            id="msg-1",
            thread_id="chat-1",
            role="assistant",
            content="Previous grounded answer",
            created_at="2026-07-23T00:00:00Z",
        )
    ]

    completion = await assistant.chat(
        {"simulation": {"id": "sim-orders"}, "scenarios": []},
        history,
        "What should I do next?",
    )

    assert completion.actions[0].kind == "compile"
    assert completion.actions[0].status == "proposed"
    assert captured["format"]["title"] == "AIChatCompletion"
    assert captured["options"]["temperature"] == 0.2
    assert "cannot execute actions" in captured["messages"][0]["content"]
    assert "sim-orders" in captured["messages"][1]["content"]
