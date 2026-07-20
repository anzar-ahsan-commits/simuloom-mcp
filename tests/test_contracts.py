import yaml

from simuloom.core.compiler import compile_wiremock_mappings
from simuloom.core.contracts import analyze_contract


def example_contract() -> dict:
    with open("examples/benefits-eligibility/openapi.yaml", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_analyze_contract() -> None:
    summary = analyze_contract(example_contract())
    assert summary.title == "Synthetic Benefits Eligibility API"
    assert summary.operations[0].operation_id == "checkEligibility"
    assert len(summary.operations) == 3
    assert len(summary.fingerprint) == 16


def test_compile_wiremock_mapping() -> None:
    mappings = compile_wiremock_mappings(example_contract())
    assert len(mappings) == 3
    assert mappings[0]["request"]["urlPathPattern"] == "^/eligibility/[^/]+$"
    assert mappings[0]["response"]["status"] == 200
