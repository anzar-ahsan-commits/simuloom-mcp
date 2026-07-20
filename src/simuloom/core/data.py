from __future__ import annotations

import random
from typing import Any

from faker import Faker


def generate_members(records: int, seed: int) -> list[dict[str, Any]]:
    """Generate fictional, correlated eligibility records; never source production data."""
    faker = Faker("en_US")
    faker.seed_instance(seed)
    rng = random.Random(seed)
    plans = [
        {"planId": "PLN-GOLD", "planName": "Synthetic Gold Plan"},
        {"planId": "PLN-SILVER", "planName": "Synthetic Silver Plan"},
        {"planId": "PLN-BRONZE", "planName": "Synthetic Bronze Plan"},
    ]
    members: list[dict[str, Any]] = []
    for index in range(records):
        plan = plans[index % len(plans)]
        active = rng.random() >= 0.2
        members.append(
            {
                "memberId": f"SYN-{seed:04d}-{index + 1:06d}",
                "firstName": faker.first_name(),
                "lastName": faker.last_name(),
                "dateOfBirth": faker.date_of_birth(minimum_age=18, maximum_age=85).isoformat(),
                "status": "ACTIVE" if active else "INACTIVE",
                "plan": plan,
                "effectiveDate": "2026-01-01",
                "synthetic": True,
            }
        )
    return members


def validate_members(members: list[dict[str, Any]]) -> None:
    for member in members:
        plan = member.get("plan")
        if (
            not isinstance(member.get("memberId"), str)
            or not member["memberId"].startswith("SYN-")
            or not isinstance(member.get("status"), str)
            or not isinstance(member.get("effectiveDate"), str)
            or not isinstance(plan, dict)
            or not isinstance(plan.get("planName"), str)
        ):
            raise ValueError("Eligibility datasets contain an invalid synthetic member record")
