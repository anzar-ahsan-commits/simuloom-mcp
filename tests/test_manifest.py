import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from simuloom.adapters.wiremock import WireMockClient
from simuloom.core.manifest import MANIFEST_VERSION
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService


def load_contract() -> dict:
    return yaml.safe_load(Path("examples/benefits-eligibility/openapi.yaml").read_text())


def create_service(tmp_path: Path) -> SimulationService:
    return SimulationService(
        WorkspaceRepository(tmp_path), WireMockClient("http://wiremock.invalid")
    )


def archive_bytes(files: dict[str, bytes]) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return target.getvalue()


def test_export_is_reproducible_and_import_round_trips(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    original = service.create("Portable Eligibility", load_contract())
    service.generate_data(original.id, records=3, seed=42)
    service.activate_profile(original.id, "slow", 1_500, 503)

    first = service.export_bundle_path(original.id).read_bytes()
    second = service.export_bundle_path(original.id).read_bytes()

    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert "simulation.yaml" in archive.namelist()
        assert "contract.json" in archive.namelist()
        assert "datasets/members.json" in archive.namelist()
        manifest = yaml.safe_load(archive.read("simulation.yaml"))
    assert manifest["apiVersion"] == MANIFEST_VERSION
    assert manifest["spec"]["data"]["classification"] == "SYNTHETIC_ONLY"
    assert manifest["spec"]["behavior"]["profile"]["name"] == "slow"

    imported = service.import_bundle(first, "eligibility.simuloom.zip")

    assert imported.simulation.id != original.id
    assert imported.simulation.status == "compiled"
    assert imported.imported_dataset_records == 3
    assert imported.active_profile == "slow"
    imported_members = service.repository.read_json(imported.simulation.id, "datasets/members.json")
    imported_mappings = service.repository.read_json(
        imported.simulation.id, "mappings/mappings.json"
    )
    assert len(imported_members) == 3
    assert imported_mappings
    assert all(member["synthetic"] is True for member in imported_members)
    assert (
        service.get(imported.simulation.id)["fingerprint"]
        == service.get(original.id)["fingerprint"]
    )


def test_import_rejects_tampered_contract(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    simulation = service.create("Tamper Check", load_contract())
    exported = service.export_bundle_path(simulation.id).read_bytes()
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    contract = json.loads(files["contract.json"])
    contract["info"]["version"] = "tampered"
    files["contract.json"] = json.dumps(contract).encode()

    with pytest.raises(ValueError, match="Contract fingerprint mismatch"):
        service.import_bundle(archive_bytes(files), "tampered.simuloom.zip")


def test_import_rejects_unsafe_archive_path(tmp_path: Path) -> None:
    service = create_service(tmp_path)
    simulation = service.create("Unsafe Path Check", load_contract())
    exported = service.export_bundle_path(simulation.id).read_bytes()
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["../outside.json"] = b"{}"

    with pytest.raises(ValueError, match="Unsafe bundle path"):
        service.import_bundle(archive_bytes(files), "unsafe.simuloom.zip")
