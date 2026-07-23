from pathlib import Path

import pytest

from simuloom.runtime.memory import MemoryRuntimeStore
from simuloom.runtime.models import (
    RuntimeMapping,
    RuntimeRequestMatcher,
    RuntimeResponseDefinition,
)
from simuloom.runtime.sqlite import SQLiteRuntimeStore


def mapping(name: str) -> RuntimeMapping:
    return RuntimeMapping(
        name=name,
        request=RuntimeRequestMatcher(method="GET", path=f"/{name}"),
        response=RuntimeResponseDefinition(status=200, json_body={"name": name}),
    )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_runtime_store_isolates_mappings_and_bounds_journal(backend: str, tmp_path: Path) -> None:
    store = (
        MemoryRuntimeStore(journal_limit=2)
        if backend == "memory"
        else SQLiteRuntimeStore(tmp_path / "runtime.db", journal_limit=2)
    )
    try:
        store.replace_mappings("one", [mapping("first")])
        store.replace_mappings("two", [mapping("second")])
        for index in range(3):
            store.append_event("one", {"simulationId": "one", "index": index})
        store.append_event("two", {"simulationId": "two", "index": 9})

        assert [item.name for item in store.mappings("one")] == ["first"]
        assert [item.name for item in store.mappings("two")] == ["second"]
        assert [event["index"] for event in store.events("one")] == [1, 2]
        assert [event["index"] for event in store.events("two")] == [9]
    finally:
        store.close()


def test_sqlite_store_restores_mappings_state_and_events(tmp_path: Path) -> None:
    path = tmp_path / "runtime.db"
    first = SQLiteRuntimeStore(path)
    first.replace_mappings("one", [mapping("persisted")])
    first.ensure_scenario_state("one", "scenario-one", "STARTED")
    first.set_scenario_state("scenario-one", "PAID")
    first.append_event("one", {"simulationId": "one", "wasMatched": True})
    first.close()

    restored = SQLiteRuntimeStore(path)
    try:
        assert restored.mappings("one")[0].name == "persisted"
        assert restored.scenario_state("scenario-one") == "PAID"
        assert restored.events("one")[0]["wasMatched"] is True
    finally:
        restored.close()


def test_sqlite_store_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "runtime.db"
    store = SQLiteRuntimeStore(path)
    store._connection.execute(  # noqa: SLF001 - controlled corruption fixture
        "UPDATE runtime_metadata SET value = '99' WHERE key = 'schema_version'"
    )
    store._connection.commit()  # noqa: SLF001 - controlled corruption fixture
    store.close()

    with pytest.raises(RuntimeError, match="Unsupported native runtime schema"):
        SQLiteRuntimeStore(path)
