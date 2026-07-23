from __future__ import annotations

from simuloom.models import ScenarioDefinition, ScenarioGraphDiagnostic


def scenario_graph_diagnostics(
    definition: ScenarioDefinition,
) -> list[ScenarioGraphDiagnostic]:
    by_name = {state.name: state for state in definition.states}
    reachable = {definition.initial_state}
    frontier = [definition.initial_state]
    while frontier:
        state_name = frontier.pop(0)
        for handler in by_name[state_name].handlers:
            if handler.new_state is not None and handler.new_state not in reachable:
                reachable.add(handler.new_state)
                frontier.append(handler.new_state)

    diagnostics: list[ScenarioGraphDiagnostic] = []
    for state in definition.states:
        if state.name not in reachable:
            diagnostics.append(
                ScenarioGraphDiagnostic(
                    severity="warning",
                    code="unreachable-state",
                    message=f"State '{state.name}' is unreachable from the initial state",
                    state=state.name,
                )
            )
        transitions = [handler for handler in state.handlers if handler.new_state is not None]
        if not transitions:
            diagnostics.append(
                ScenarioGraphDiagnostic(
                    severity="info",
                    code="terminal-state",
                    message=f"State '{state.name}' has no outgoing transitions",
                    state=state.name,
                )
            )
        for handler in transitions:
            if handler.new_state == state.name:
                diagnostics.append(
                    ScenarioGraphDiagnostic(
                        severity="info",
                        code="self-transition",
                        message=f"Handler '{handler.name}' transitions back to '{state.name}'",
                        state=state.name,
                        handler=handler.name,
                    )
                )
    return diagnostics
