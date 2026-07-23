from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock

from simuloom.core.repository import WorkspaceRepository
from simuloom.models import ScenarioReleasePolicy, ScenarioReview, ScenarioRevision


class ScenarioApprovalError(RuntimeError):
    pass


class ScenarioApprovalStore:
    def __init__(self, repository: WorkspaceRepository):
        self.repository = repository
        self._lock = RLock()

    def policy(self, simulation_id: str) -> ScenarioReleasePolicy:
        try:
            payload = self.repository.read_json(simulation_id, "scenarios/release-policy.json")
        except FileNotFoundError:
            return ScenarioReleasePolicy()
        return ScenarioReleasePolicy.model_validate(payload)

    def update_policy(
        self,
        simulation_id: str,
        require_approval: bool,
        block_breaking_changes: bool,
        actor: str,
    ) -> ScenarioReleasePolicy:
        policy = ScenarioReleasePolicy(
            require_approval=require_approval,
            block_breaking_changes=block_breaking_changes,
            updated_at=datetime.now(UTC),
            updated_by=actor,
        )
        self.repository.write_json(
            simulation_id,
            "scenarios/release-policy.json",
            policy.model_dump(mode="json"),
        )
        return policy

    def request(self, revision: ScenarioRevision, actor: str, note: str = "") -> ScenarioReview:
        with self._lock:
            reviews = self._read(revision.simulation_id, revision.scenario_id)
            if any(
                item.revision == revision.revision and item.status == "pending" for item in reviews
            ):
                raise ValueError("This scenario revision already has a pending review")
            review = ScenarioReview(
                simulation_id=revision.simulation_id,
                scenario_id=revision.scenario_id,
                review_number=len(reviews) + 1,
                revision=revision.revision,
                etag=revision.etag,
                status="pending",
                requested_at=datetime.now(UTC),
                requested_by=actor,
                request_note=note,
            )
            reviews.append(review)
            self._write(revision.simulation_id, revision.scenario_id, reviews)
            return review

    def decide(
        self,
        simulation_id: str,
        scenario_id: str,
        review_number: int,
        approved: bool,
        actor: str,
        note: str = "",
    ) -> ScenarioReview:
        with self._lock:
            reviews = self._read(simulation_id, scenario_id)
            if review_number < 1 or review_number > len(reviews):
                raise KeyError(f"Scenario review not found: {review_number}")
            review = reviews[review_number - 1]
            if review.status != "pending":
                raise ValueError("Scenario review has already been decided")
            decided = review.model_copy(
                update={
                    "status": "approved" if approved else "rejected",
                    "decided_at": datetime.now(UTC),
                    "decided_by": actor,
                    "decision_note": note,
                }
            )
            reviews[review_number - 1] = decided
            self._write(simulation_id, scenario_id, reviews)
            return decided

    def list(self, simulation_id: str, scenario_id: str) -> list[ScenarioReview]:
        return list(reversed(self._read(simulation_id, scenario_id)))

    def require_deployable(self, revision: ScenarioRevision) -> None:
        policy = self.policy(revision.simulation_id)
        if not policy.require_approval:
            return
        approved = any(
            item.revision == revision.revision
            and item.etag == revision.etag
            and item.status == "approved"
            for item in self._read(revision.simulation_id, revision.scenario_id)
        )
        if not approved:
            raise ScenarioApprovalError(
                f"Scenario revision {revision.revision} requires approval before deployment"
            )

    def _read(self, simulation_id: str, scenario_id: str) -> list[ScenarioReview]:
        self.repository.validate_scenario_id(scenario_id)
        try:
            payload = self.repository.read_json(
                simulation_id, f"scenarios/reviews/{scenario_id}.json"
            )
        except FileNotFoundError:
            return []
        if not isinstance(payload, list):
            raise ValueError("Stored scenario reviews must be an array")
        return [ScenarioReview.model_validate(item) for item in payload]

    def _write(self, simulation_id: str, scenario_id: str, reviews: list[ScenarioReview]) -> None:
        self.repository.write_json(
            simulation_id,
            f"scenarios/reviews/{scenario_id}.json",
            [item.model_dump(mode="json") for item in reviews],
        )
