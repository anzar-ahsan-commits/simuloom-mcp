from pathlib import Path

import pytest
from test_scenarios import ScenarioWireMock, contract, definition_payload

from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.models import ScenarioDefinition


@pytest.fixture
def template_service(tmp_path: Path) -> SimulationService:
    return SimulationService(WorkspaceRepository(tmp_path), ScenarioWireMock())  # type: ignore[arg-type]


def test_template_create_list_and_contract_validated_instantiation(
    template_service: SimulationService,
) -> None:
    source = template_service.create("Template source", contract())
    target = template_service.create("Template target", contract())
    template_service.configure_scenario(
        source.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )

    template = template_service.create_scenario_template(
        source.id,
        "order-lifecycle",
        1,
        "standard-order-lifecycle",
        "Standard order lifecycle",
        "Reusable order workflow",
        "template-author",
    )
    instantiated = template_service.instantiate_scenario_template(
        template.template_id, target.id, "orders", "template-user"
    )

    assert template.source_revision == 1
    assert template_service.scenario_templates()[0] == template
    assert template_service.get_scenario_template(template.template_id) == template
    assert instantiated.scenario_id == "orders"
    assert instantiated.updated_by == "template-user"


def test_template_ids_are_unique(template_service: SimulationService) -> None:
    source = template_service.create("Template uniqueness", contract())
    template_service.configure_scenario(
        source.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    template_service.create_scenario_template(
        source.id, "order-lifecycle", 1, "orders", "Orders", "", "author"
    )

    with pytest.raises(ValueError, match="already exists"):
        template_service.create_scenario_template(
            source.id, "order-lifecycle", 1, "orders", "Orders", "", "author"
        )


def test_parameterized_template_instances(template_service: SimulationService) -> None:
    source = template_service.create("Parameterized source", contract())
    target = template_service.create("Parameterized target", contract())
    template_service.configure_scenario(
        source.id,
        "order-lifecycle",
        ScenarioDefinition.model_validate(definition_payload()),
    )
    template = template_service.create_scenario_template(
        source.id,
        "order-lifecycle",
        1,
        "parameterized-orders",
        "Parameterized orders",
        "",
        "author",
        {"ORDER_ID": "ORD-SYN-1"},
    )

    with pytest.raises(ValueError, match="missing=.*ORDER_ID"):
        template_service.instantiate_scenario_template(
            template.template_id, target.id, "orders", "user"
        )
    instance = template_service.instantiate_scenario_template(
        template.template_id,
        target.id,
        "orders",
        "user",
        parameters={"ORDER_ID": "ORD-TARGET"},
    )

    assert template.parameters == ["ORDER_ID"]
    assert "${ORDER_ID}" in template.model_dump_json()
    assert "ORD-TARGET" in instance.definition.model_dump_json()
    assert "${ORDER_ID}" not in instance.definition.model_dump_json()
