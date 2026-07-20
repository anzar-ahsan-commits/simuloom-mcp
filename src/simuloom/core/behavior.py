from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

SUPPORTED_PROFILES = {"normal", "slow", "unavailable", "intermittent"}


def apply_behavior_profile(
    mappings: list[dict[str, Any]],
    profile: str,
    simulation_id: str,
    fixed_delay_ms: int,
    failure_status: int,
) -> list[dict[str, Any]]:
    if profile not in SUPPORTED_PROFILES:
        raise ValueError(f"Unsupported behavior profile: {profile}")
    if profile == "normal":
        return mappings

    if profile == "slow":
        delayed = deepcopy(mappings)
        for mapping in delayed:
            mapping["response"]["fixedDelayMilliseconds"] = fixed_delay_ms
            mapping.setdefault("metadata", {})["simuloomProfile"] = profile
        return delayed

    if profile == "unavailable":
        unavailable = deepcopy(mappings)
        for mapping in unavailable:
            mapping["response"] = {
                "status": failure_status,
                "headers": {
                    "Content-Type": "application/json",
                    "Retry-After": "5",
                    "X-SimuLoom-Profile": profile,
                },
                "body": json.dumps(
                    {
                        "code": "SIMULATED_DEPENDENCY_UNAVAILABLE",
                        "message": "SimuLoom intentionally made this dependency unavailable",
                        "synthetic": True,
                    }
                ),
            }
            mapping.setdefault("metadata", {})["simuloomProfile"] = profile
        return unavailable

    scenario_name = f"SimuLoom intermittent - {simulation_id}"
    intermittent: list[dict[str, Any]] = []
    for mapping in mappings:
        # Contract-backed business journeys already own their scenario state machine.
        if "scenarioName" in mapping:
            intermittent.append(mapping)
            continue

        success = deepcopy(mapping)
        success["scenarioName"] = scenario_name
        success["requiredScenarioState"] = "Started"
        success["newScenarioState"] = "DEGRADED"
        success.setdefault("metadata", {})["simuloomProfile"] = profile

        failure = deepcopy(mapping)
        failure["name"] = f"{mapping.get('name', 'SimuLoom mapping')} - intermittent failure"
        failure["scenarioName"] = scenario_name
        failure["requiredScenarioState"] = "DEGRADED"
        failure["newScenarioState"] = "Started"
        failure["response"] = {
            "status": failure_status,
            "headers": {
                "Content-Type": "application/json",
                "Retry-After": "1",
                "X-SimuLoom-Profile": profile,
            },
            "body": json.dumps(
                {
                    "code": "SIMULATED_INTERMITTENT_FAILURE",
                    "message": "This deterministic failure alternates with the normal response",
                    "synthetic": True,
                }
            ),
        }
        failure.setdefault("metadata", {})["simuloomProfile"] = profile
        intermittent.extend((success, failure))
    return intermittent
