import pytest

from simuloom.adapters.native import NativeRuntimeAdapter
from simuloom.config import Settings
from simuloom.runtime.translation import from_wiremock_mappings, to_wiremock_mapping


def wiremock_mappings() -> list[dict]:
    return [
        {
            "name": "create order",
            "priority": 1,
            "scenarioName": "orders",
            "requiredScenarioState": "Started",
            "newScenarioState": "PENDING",
            "request": {
                "method": "POST",
                "urlPath": "/orders",
                "queryParameters": {"source": {"equalTo": "test"}},
                "headers": {"X-Tenant": {"equalTo": "synthetic"}},
                "bodyPatterns": [{"equalToJson": '{"quantity": 1}'}],
            },
            "response": {
                "status": 201,
                "headers": {"Content-Type": "application/json"},
                "body": '{"status":"PENDING"}',
            },
            "metadata": {"simuloomSimulationId": "one"},
        },
        {
            "name": "pending order",
            "priority": 1,
            "scenarioName": "orders",
            "requiredScenarioState": "PENDING",
            "request": {"method": "GET", "urlPath": "/orders/ONE"},
            "response": {"status": 200, "body": '{"status":"PENDING"}'},
        },
        {
            "name": "fallback",
            "priority": 10,
            "request": {"method": "GET", "urlPathPattern": "^/orders/[^/]+$"},
            "response": {"status": 404, "body": '{"code":"NOT_FOUND"}'},
        },
    ]


def test_wiremock_translation_round_trip_preserves_behavior_fields() -> None:
    canonical = from_wiremock_mappings(wiremock_mappings())
    restored = to_wiremock_mapping(canonical[0])

    assert canonical[0].request.json_body == {"quantity": 1}
    assert canonical[0].response.json_body == {"status": "PENDING"}
    assert restored["scenarioName"] == "orders"
    assert restored["requiredScenarioState"] == "Started"
    assert restored["newScenarioState"] == "PENDING"
    assert restored["request"]["queryParameters"]["source"] == {"equalTo": "test"}


def test_runtime_selection_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMULOOM_RUNTIME", "native")
    monkeypatch.setenv("SIMULOOM_NATIVE_RUNTIME_URL", "http://native.test/runtime/")

    settings = Settings.from_env()

    assert settings.runtime == "native"
    assert settings.native_runtime_url == "http://native.test/runtime"


def test_unknown_runtime_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMULOOM_RUNTIME", "unknown")

    with pytest.raises(ValueError, match="wiremock or native"):
        Settings.from_env()


@pytest.mark.asyncio
async def test_native_runtime_matches_transitions_priorities_and_journal() -> None:
    runtime = NativeRuntimeAdapter()
    mappings = from_wiremock_mappings(wiremock_mappings())
    await runtime.deploy(mappings, reset_existing=False, simulation_id="one")

    unmatched = await runtime.execute("GET", "/unknown", simulation_id="one")
    created = await runtime.execute(
        "POST",
        "/orders?source=test",
        {"quantity": 1},
        {"x-tenant": "synthetic"},
        simulation_id="one",
    )
    pending = await runtime.execute("GET", "/orders/ONE", simulation_id="one")
    fallback = await runtime.execute("GET", "/orders/TWO", simulation_id="one")

    assert unmatched.status_code == 404
    assert created.status_code == 201
    assert pending.body == {"status": "PENDING"}
    assert fallback.body == {"code": "NOT_FOUND"}
    assert await runtime.scenario_state("orders") == "PENDING"
    events = await runtime.serve_events("one")
    assert [event["wasMatched"] for event in events] == [False, True, True, True]


@pytest.mark.asyncio
async def test_native_runtime_scopes_deployments_and_resets() -> None:
    runtime = NativeRuntimeAdapter()
    mappings = from_wiremock_mappings(wiremock_mappings())
    await runtime.deploy(mappings, False, simulation_id="one")
    await runtime.deploy(mappings, False, simulation_id="two")
    await runtime.execute("GET", "/orders/TWO", simulation_id="one")
    await runtime.execute("GET", "/orders/TWO", simulation_id="two")

    await runtime.reset_runtime_state("one")

    assert await runtime.serve_events("one") == []
    assert len(await runtime.serve_events("two")) == 1
    assert runtime.capabilities().runtime == "native"
