from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from typing import Any

from simuloom.models import ContractSummary, OperationSummary

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
ELIGIBILITY_OPERATIONS = {
    "checkEligibility",
    "beginEligibilityRequest",
    "getEligibilityRequest",
}


def contract_fingerprint(contract: dict[str, Any]) -> str:
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


def operation_identifier(method: str, path: str, operation: dict[str, Any]) -> str:
    declared = operation.get("operationId")
    if declared:
        return str(declared)
    normalized_path = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root"
    return f"{method.lower()}_{normalized_path}"


def iter_operations(
    contract: dict[str, Any],
) -> Iterator[tuple[str, dict[str, Any], str, dict[str, Any]]]:
    for path, path_item in (contract.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                yield str(path), path_item, method.upper(), operation


def is_eligibility_contract(contract: dict[str, Any]) -> bool:
    operation_ids = {
        operation_identifier(method, path, operation)
        for path, _, method, operation in iter_operations(contract)
    }
    return ELIGIBILITY_OPERATIONS <= operation_ids


def analyze_contract(contract: dict[str, Any]) -> ContractSummary:
    openapi_version = str(contract.get("openapi", ""))
    if not openapi_version.startswith("3."):
        raise ValueError("SimuLoom currently requires an OpenAPI 3.x document")

    info = contract.get("info") or {}
    paths = contract.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("The OpenAPI document does not contain any paths")

    operations: list[OperationSummary] = []
    warnings: list[str] = []
    operation_ids: set[str] = set()
    for path, _, method, operation in iter_operations(contract):
        operation_id = operation_identifier(method, path, operation)
        if not operation.get("operationId"):
            warnings.append(f"{method} {path} has no operationId; using {operation_id}")
        if operation_id in operation_ids:
            warnings.append(f"Operation identifier {operation_id} is duplicated")
        operation_ids.add(operation_id)
        responses = operation.get("responses") or {}
        operations.append(
            OperationSummary(
                operation_id=operation_id,
                method=method,
                path=path,
                response_codes=[str(code) for code in responses],
            )
        )

    if not operations:
        raise ValueError("The OpenAPI document contains no HTTP operations")

    return ContractSummary(
        title=str(info.get("title", "Untitled API")),
        version=str(info.get("version", "unversioned")),
        openapi_version=openapi_version,
        fingerprint=contract_fingerprint(contract),
        operations=operations,
        warnings=warnings,
    )
