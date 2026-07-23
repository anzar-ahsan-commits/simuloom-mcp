from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from simuloom.core.repository import WorkspaceRepository
from simuloom.models import ScenarioDefinition, ScenarioRevision, ScenarioTemplate


class ScenarioTemplateStore:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository
        self.root = repository.root / "templates"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        template_id: str,
        name: str,
        description: str,
        revision: ScenarioRevision,
        actor: str,
        parameterize: dict[str, str] | None = None,
    ) -> ScenarioTemplate:
        self._validate_id(template_id)
        path = self.root / f"{template_id}.json"
        if path.exists():
            raise ValueError(f"Scenario template already exists: {template_id}")
        substitutions = parameterize or {}
        if any(not key or not value for key, value in substitutions.items()):
            raise ValueError("Template parameter names and source values must be non-empty")
        payload = _replace_literals(revision.definition.model_dump(mode="json"), substitutions)
        template = ScenarioTemplate(
            template_id=template_id,
            name=name,
            description=description,
            definition=ScenarioDefinition.model_validate(payload),
            created_at=datetime.now(UTC),
            created_by=actor,
            source_simulation_id=revision.simulation_id,
            source_scenario_id=revision.scenario_id,
            source_revision=revision.revision,
            parameters=sorted(substitutions),
        )
        path.write_text(template.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return template

    def get(self, template_id: str) -> ScenarioTemplate:
        self._validate_id(template_id)
        path = self.root / f"{template_id}.json"
        if not path.is_file():
            raise KeyError(f"Scenario template not found: {template_id}")
        return ScenarioTemplate.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[ScenarioTemplate]:
        return [
            ScenarioTemplate.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.root.glob("*.json"))
        ]

    def render(self, template_id: str, parameters: dict[str, str]) -> ScenarioDefinition:
        template = self.get(template_id)
        expected = set(template.parameters)
        supplied = set(parameters)
        if expected != supplied:
            raise ValueError(
                "Template parameters mismatch; "
                f"missing={sorted(expected - supplied)}, extra={sorted(supplied - expected)}"
            )
        return ScenarioDefinition.model_validate(
            _replace_placeholders(template.definition.model_dump(mode="json"), parameters)
        )

    @staticmethod
    def _validate_id(template_id: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", template_id):
            raise ValueError("Invalid scenario template id")


def _replace_literals(value, substitutions: dict[str, str]):
    if isinstance(value, dict):
        return {key: _replace_literals(item, substitutions) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_literals(item, substitutions) for item in value]
    if isinstance(value, str):
        for name, literal in substitutions.items():
            value = value.replace(literal, f"${{{name}}}")
    return value


def _replace_placeholders(value, parameters: dict[str, str]):
    if isinstance(value, dict):
        return {key: _replace_placeholders(item, parameters) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item, parameters) for item in value]
    if isinstance(value, str):
        for name, replacement in parameters.items():
            value = value.replace(f"${{{name}}}", replacement)
    return value
