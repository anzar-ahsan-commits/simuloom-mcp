import hashlib
import hmac
import json

import httpx
import pytest

from simuloom.core.integrations import IntegrationDispatcher
from simuloom.core.platform_store import PlatformStore


def test_integration_endpoint_requires_https_and_explicit_host() -> None:
    dispatcher = IntegrationDispatcher(frozenset({"hooks.example.com"}), "secret")

    assert (
        dispatcher.validate_endpoint("https://hooks.example.com/simuloom")
        == "https://hooks.example.com/simuloom"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        dispatcher.validate_endpoint("http://hooks.example.com/simuloom")
    with pytest.raises(ValueError, match="allowlisted"):
        dispatcher.validate_endpoint("https://127.0.0.1/internal")
    with pytest.raises(ValueError, match="credentials"):
        dispatcher.validate_endpoint("https://user:password@hooks.example.com/simuloom")


@pytest.mark.asyncio
async def test_delivery_is_signed_and_idempotent() -> None:
    captured: dict[str, object] = {}

    def receive(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = request.content
        return httpx.Response(202)

    dispatcher = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "signing-secret",
        transport=httpx.MockTransport(receive),
    )
    integration = {
        "endpoint": "https://hooks.example.com/simuloom",
        "event_types": ["scenario.deployed"],
    }

    result = await dispatcher.dispatch(
        integration, "scenario.deployed", {"scenario_id": "order-flow"}
    )

    headers = captured["headers"]
    body = captured["body"]
    assert isinstance(headers, httpx.Headers)
    assert isinstance(body, bytes)
    expected = hmac.new(b"signing-secret", body, hashlib.sha256).hexdigest()
    assert headers["x-simuloom-signature"] == f"sha256={expected}"
    assert headers["idempotency-key"] == result["delivery_id"]
    assert json.loads(body)["payload"] == {"scenario_id": "order-flow"}
    assert result["accepted"] is True


@pytest.mark.asyncio
async def test_delivery_rejects_unsubscribed_event() -> None:
    dispatcher = IntegrationDispatcher(frozenset({"hooks.example.com"}), "secret")

    with pytest.raises(ValueError, match="does not subscribe"):
        await dispatcher.dispatch(
            {"endpoint": "https://hooks.example.com", "event_types": ["scenario.saved"]},
            "scenario.deployed",
            {},
        )


@pytest.mark.asyncio
async def test_transient_delivery_retries_with_same_idempotency_key() -> None:
    keys: list[str] = []

    def receive(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["idempotency-key"])
        return httpx.Response(503 if len(keys) == 1 else 202)

    dispatcher = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "secret",
        transport=httpx.MockTransport(receive),
    )

    result = await dispatcher.dispatch(
        {"endpoint": "https://hooks.example.com", "event_types": ["scenario.deployed"]},
        "scenario.deployed",
        {},
    )

    assert result["accepted"] is True
    assert result["attempts"] == 2
    assert len(set(keys)) == 1


@pytest.mark.asyncio
async def test_circuit_opens_after_repeated_transient_failures() -> None:
    dispatcher = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "secret",
        transport=httpx.MockTransport(lambda _: httpx.Response(503)),
        max_attempts=1,
        circuit_threshold=2,
    )
    integration = {
        "endpoint": "https://hooks.example.com",
        "event_types": ["scenario.deployed"],
    }

    await dispatcher.dispatch(integration, "scenario.deployed", {})
    await dispatcher.dispatch(integration, "scenario.deployed", {})
    with pytest.raises(RuntimeError, match="circuit is open"):
        await dispatcher.dispatch(integration, "scenario.deployed", {})


@pytest.mark.asyncio
async def test_circuit_state_survives_dispatcher_restart(tmp_path) -> None:
    store = PlatformStore(tmp_path / "platform.db")
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    integration = {
        "endpoint": "https://hooks.example.com",
        "event_types": ["scenario.deployed"],
    }
    first = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "secret",
        transport=transport,
        max_attempts=1,
        circuit_threshold=1,
        circuit_store=store,
    )
    await first.dispatch(integration, "scenario.deployed", {})
    second = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "secret",
        transport=transport,
        max_attempts=1,
        circuit_threshold=1,
        circuit_store=store,
    )

    with pytest.raises(RuntimeError, match="circuit is open"):
        await second.dispatch(integration, "scenario.deployed", {})


@pytest.mark.asyncio
async def test_workspace_secret_overrides_global_signing_key() -> None:
    signatures: list[str] = []

    def receive(request: httpx.Request) -> httpx.Response:
        signatures.append(request.headers["x-simuloom-signature"])
        expected = hmac.new(b"workspace-secret", request.content, hashlib.sha256).hexdigest()
        assert signatures[-1] == f"sha256={expected}"
        return httpx.Response(202)

    dispatcher = IntegrationDispatcher(
        frozenset({"hooks.example.com"}),
        "global-secret",
        transport=httpx.MockTransport(receive),
    )

    await dispatcher.dispatch(
        {"endpoint": "https://hooks.example.com", "event_types": ["scenario.deployed"]},
        "scenario.deployed",
        {},
        "workspace-secret",
    )
