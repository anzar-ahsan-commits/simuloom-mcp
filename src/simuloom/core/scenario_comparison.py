from __future__ import annotations

from typing import Any

from simuloom.models import (
    ScenarioDefinition,
    ScenarioRevisionChange,
    ScenarioRevisionComparison,
)


def compare_scenario_revisions(
    simulation_id: str,
    scenario_id: str,
    from_revision: int,
    before: ScenarioDefinition,
    to_revision: int,
    after: ScenarioDefinition,
) -> ScenarioRevisionComparison:
    changes: list[ScenarioRevisionChange] = []
    _compare_value(changes, "name", before.name, after.name)
    _compare_value(changes, "description", before.description, after.description)
    _compare_value(
        changes, "initial_state", before.initial_state, after.initial_state, breaking=True
    )
    _compare_value(changes, "reset_state", before.reset_state, after.reset_state)

    before_states = {state.name: state for state in before.states}
    after_states = {state.name: state for state in after.states}
    for name in sorted(before_states.keys() | after_states.keys()):
        path = f"states/{name}"
        if name not in before_states:
            changes.append(
                ScenarioRevisionChange(
                    path=path,
                    kind="added",
                    after=after_states[name].model_dump(mode="json"),
                )
            )
            continue
        if name not in after_states:
            changes.append(
                ScenarioRevisionChange(
                    path=path,
                    kind="removed",
                    breaking=True,
                    before=before_states[name].model_dump(mode="json"),
                )
            )
            continue
        _compare_handlers(changes, path, before_states[name].handlers, after_states[name].handlers)

    return ScenarioRevisionComparison(
        simulation_id=simulation_id,
        scenario_id=scenario_id,
        from_revision=from_revision,
        to_revision=to_revision,
        change_count=len(changes),
        breaking_change_count=sum(change.breaking for change in changes),
        changes=changes,
    )


def _compare_handlers(
    changes: list[ScenarioRevisionChange], path: str, before: list, after: list
) -> None:
    before_handlers = {handler.name: handler for handler in before}
    after_handlers = {handler.name: handler for handler in after}
    for name in sorted(before_handlers.keys() | after_handlers.keys()):
        handler_path = f"{path}/handlers/{name}"
        if name not in before_handlers:
            changes.append(
                ScenarioRevisionChange(
                    path=handler_path,
                    kind="added",
                    after=after_handlers[name].model_dump(mode="json"),
                )
            )
        elif name not in after_handlers:
            changes.append(
                ScenarioRevisionChange(
                    path=handler_path,
                    kind="removed",
                    breaking=True,
                    before=before_handlers[name].model_dump(mode="json"),
                )
            )
        else:
            before_payload = before_handlers[name].model_dump(mode="json")
            after_payload = after_handlers[name].model_dump(mode="json")
            for field in sorted(before_payload.keys() | after_payload.keys()):
                _compare_value(
                    changes,
                    f"{handler_path}/{field}",
                    before_payload.get(field),
                    after_payload.get(field),
                    breaking=field in {"request", "new_state"},
                )


def _compare_value(
    changes: list[ScenarioRevisionChange],
    path: str,
    before: Any,
    after: Any,
    breaking: bool = False,
) -> None:
    if before != after:
        changes.append(
            ScenarioRevisionChange(
                path=path,
                kind="modified",
                breaking=breaking,
                before=before,
                after=after,
            )
        )
