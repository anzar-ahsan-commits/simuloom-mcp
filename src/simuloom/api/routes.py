import re
from typing import Annotated

import yaml
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from simuloom.container import service
from simuloom.core.manifest import MAX_BUNDLE_SIZE
from simuloom.core.scenario_revisions import ScenarioConflictError
from simuloom.models import (
    CompileResult,
    ContractRequest,
    ContractSummary,
    CreateSimulationRequest,
    DataGenerationRequest,
    DataGenerationResult,
    DatasetView,
    DeployRequest,
    DeployResult,
    EvidenceReport,
    ExportResult,
    ImportResult,
    OperationSummary,
    ProfileConfigRequest,
    ProfileResult,
    ScenarioCompileResult,
    ScenarioDefinition,
    ScenarioDeployResult,
    ScenarioGraphDiagnostic,
    ScenarioRelease,
    ScenarioResetAllResult,
    ScenarioResetResult,
    ScenarioRevision,
    ScenarioRevisionComparison,
    ScenarioRevisionSummary,
    ScenarioRuntimeState,
    ScenarioSummary,
    ScenarioView,
    SessionView,
    Simulation,
    SimulationSummary,
    ValidationPlan,
    ValidationPlanRequest,
    ValidationRequest,
)
from simuloom.runtime.models import RuntimeCapabilities
from simuloom.security import Principal, Role, require_role, role_allows

router = APIRouter(prefix="/api/v1")
MAX_CONTRACT_UPLOAD_SIZE = 2 * 1024 * 1024
ViewerPrincipal = Annotated[Principal, Depends(require_role(Role.VIEWER))]
OperatorPrincipal = Annotated[Principal, Depends(require_role(Role.OPERATOR))]
AdminPrincipal = Annotated[Principal, Depends(require_role(Role.ADMIN))]


def _etag_header(etag: str) -> str:
    return f'"{etag}"'


def _parse_if_match(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if normalized.startswith("W/"):
        raise ValueError("If-Match requires a strong ETag")
    if normalized.startswith('"') and normalized.endswith('"'):
        normalized = normalized[1:-1]
    elif '"' in normalized:
        raise ValueError("If-Match contains an invalid ETag")
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ValueError("If-Match must contain one SimuLoom scenario ETag")
    return normalized


@router.get("/health")
async def health() -> dict[str, str | bool]:
    try:
        runtime_ready = await service.runtime.health()
    except Exception:
        runtime_ready = False
    runtime_name = service.runtime.capabilities().runtime
    return {
        "status": "ok",
        "runtime": runtime_name,
        "runtimeReady": runtime_ready,
        "wiremockReady": runtime_ready if runtime_name == "wiremock" else False,
    }


@router.get("/runtime", response_model=RuntimeCapabilities)
def runtime_capabilities(_principal: ViewerPrincipal) -> RuntimeCapabilities:
    return service.runtime.capabilities()


@router.get("/session", response_model=SessionView)
def current_session(principal: ViewerPrincipal) -> SessionView:
    return SessionView(
        subject=principal.subject,
        role=principal.role.value,
        authentication_enabled=principal.key_id is not None,
    )


@router.post("/contracts/analyze", response_model=ContractSummary)
def analyze_contract(request: ContractRequest, _principal: ViewerPrincipal) -> ContractSummary:
    try:
        return service.analyze(request.contract)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/simulations", response_model=Simulation, status_code=201)
def create_simulation(
    request: CreateSimulationRequest, _principal: OperatorPrincipal
) -> Simulation:
    try:
        return service.create(request.name, request.contract)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/simulations", response_model=list[SimulationSummary])
def list_simulations(_principal: ViewerPrincipal) -> list[SimulationSummary]:
    return service.list_simulations()


@router.post("/simulations/from-contract", response_model=Simulation, status_code=201)
async def create_simulation_from_contract(
    name: Annotated[
        str,
        Form(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._ -]+$"),
    ],
    contract: Annotated[UploadFile, File()],
    _principal: OperatorPrincipal,
) -> Simulation:
    data = await contract.read(MAX_CONTRACT_UPLOAD_SIZE + 1)
    if len(data) > MAX_CONTRACT_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="Contract upload exceeds 2 MiB")
    try:
        payload = yaml.safe_load(data)
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise HTTPException(status_code=422, detail="Contract must be valid YAML or JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Contract must be a YAML or JSON object")
    try:
        return service.create(name, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: str, _principal: ViewerPrincipal) -> dict:
    try:
        return service.get(simulation_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}/operations", response_model=list[OperationSummary])
def simulation_operations(
    simulation_id: str, _principal: ViewerPrincipal
) -> list[OperationSummary]:
    try:
        return service.contract_operations(simulation_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/simulations/{simulation_id}/data", response_model=DataGenerationResult)
def generate_data(
    simulation_id: str, request: DataGenerationRequest, _principal: OperatorPrincipal
) -> DataGenerationResult:
    try:
        return service.generate_data(simulation_id, request.records, request.seed)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}/data", response_model=DatasetView)
def get_dataset(simulation_id: str, _principal: ViewerPrincipal) -> DatasetView:
    try:
        return service.get_dataset(simulation_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/simulations/{simulation_id}/compile", response_model=CompileResult)
def compile_simulation(simulation_id: str, _principal: OperatorPrincipal) -> CompileResult:
    try:
        return service.compile(simulation_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/simulations/{simulation_id}/profiles/{profile}", response_model=ProfileResult)
def activate_profile(
    simulation_id: str,
    profile: str,
    request: ProfileConfigRequest,
    _principal: OperatorPrincipal,
) -> ProfileResult:
    try:
        return service.activate_profile(
            simulation_id, profile, request.fixed_delay_ms, request.failure_status
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/simulations/{simulation_id}/deploy", response_model=DeployResult)
async def deploy_simulation(
    simulation_id: str, request: DeployRequest, principal: OperatorPrincipal
) -> DeployResult:
    if request.reset_existing and not role_allows(principal.role, Role.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="The admin role is required to reset existing WireMock mappings",
        )
    try:
        return await service.deploy(simulation_id, request.reset_existing, actor=principal.subject)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Runtime deployment failed: {exc}") from exc


@router.post("/simulations/{simulation_id}/validate", response_model=EvidenceReport)
async def validate_simulation(
    simulation_id: str, request: ValidationRequest, _principal: OperatorPrincipal
) -> EvidenceReport:
    try:
        return await service.validate(
            simulation_id,
            request.max_dataset_cases,
            request.reset_runtime_state,
            request.include_boundary_cases,
            request.include_negative_cases,
            request.max_edge_cases_per_operation,
            request.include_pairwise_cases,
            request.max_pairwise_cases_per_operation,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Validation execution failed: {exc}") from exc


@router.post("/simulations/{simulation_id}/validation/plan", response_model=ValidationPlan)
def plan_validation(
    simulation_id: str,
    request: ValidationPlanRequest,
    _principal: ViewerPrincipal,
) -> ValidationPlan:
    try:
        return service.plan_validation(
            simulation_id,
            request.max_dataset_cases,
            request.include_boundary_cases,
            request.include_negative_cases,
            request.max_edge_cases_per_operation,
            request.include_pairwise_cases,
            request.max_pairwise_cases_per_operation,
        )
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}/reports/latest", response_model=EvidenceReport)
def latest_report(simulation_id: str, _principal: ViewerPrincipal) -> EvidenceReport:
    try:
        return service.latest_report(simulation_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/reports/latest/html",
    response_class=HTMLResponse,
)
def latest_report_html(simulation_id: str, _principal: ViewerPrincipal) -> HTMLResponse:
    try:
        return HTMLResponse(service.latest_report_html(simulation_id))
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/simulations/{simulation_id}/export", response_model=ExportResult)
def export_simulation(simulation_id: str, _principal: ViewerPrincipal) -> ExportResult:
    try:
        return service.export_bundle(simulation_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}/manifest", response_class=PlainTextResponse)
def portable_manifest(simulation_id: str, _principal: ViewerPrincipal) -> PlainTextResponse:
    try:
        return PlainTextResponse(
            service.portable_manifest(simulation_id), media_type="application/yaml"
        )
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}/export/bundle", response_class=FileResponse)
def export_simulation_bundle(simulation_id: str, _principal: ViewerPrincipal) -> FileResponse:
    try:
        path = service.export_bundle_path(simulation_id)
        return FileResponse(path, filename=path.name, media_type="application/zip")
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/simulations/import", response_model=ImportResult, status_code=201)
async def import_simulation(
    bundle: Annotated[UploadFile, File()], _principal: OperatorPrincipal
) -> ImportResult:
    try:
        data = await bundle.read(MAX_BUNDLE_SIZE + 1)
        return service.import_bundle(data, bundle.filename or "uploaded-bundle")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/simulations/{simulation_id}/scenarios", response_model=list[ScenarioSummary])
def list_scenarios(simulation_id: str, _principal: ViewerPrincipal) -> list[ScenarioSummary]:
    try:
        return service.list_scenarios(simulation_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/simulations/{simulation_id}/scenarios/{scenario_id}",
    response_model=ScenarioView,
)
def configure_scenario(
    simulation_id: str,
    scenario_id: str,
    definition: ScenarioDefinition,
    principal: OperatorPrincipal,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ScenarioView:
    try:
        view = service.configure_scenario(
            simulation_id,
            scenario_id,
            definition,
            principal.subject,
            _parse_if_match(if_match),
        )
        response.headers["ETag"] = _etag_header(view.etag)
        return view
    except ScenarioConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scenario-edit-conflict",
                "message": str(exc),
                "expected_etag": exc.expected_etag,
                "current_etag": exc.current_etag,
                "current_revision": exc.current_revision,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}",
    response_model=ScenarioView,
)
def get_scenario(
    simulation_id: str,
    scenario_id: str,
    _principal: ViewerPrincipal,
    response: Response,
) -> ScenarioView:
    try:
        view = service.get_scenario(simulation_id, scenario_id)
        response.headers["ETag"] = _etag_header(view.etag)
        return view
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history",
    response_model=list[ScenarioRevisionSummary],
)
def scenario_history(
    simulation_id: str,
    scenario_id: str,
    _principal: ViewerPrincipal,
) -> list[ScenarioRevisionSummary]:
    try:
        return service.scenario_history(simulation_id, scenario_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/compare",
    response_model=ScenarioRevisionComparison,
)
def compare_scenario_revisions(
    simulation_id: str,
    scenario_id: str,
    from_revision: int,
    to_revision: int,
    _principal: ViewerPrincipal,
) -> ScenarioRevisionComparison:
    try:
        return service.compare_scenario_revisions(
            simulation_id, scenario_id, from_revision, to_revision
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/{revision}",
    response_model=ScenarioRevision,
)
def get_scenario_revision(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    _principal: ViewerPrincipal,
) -> ScenarioRevision:
    try:
        return service.scenario_revision(simulation_id, scenario_id, revision)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/{revision}/restore",
    response_model=ScenarioView,
)
def restore_scenario_revision(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    principal: OperatorPrincipal,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> ScenarioView:
    try:
        view = service.restore_scenario_revision(
            simulation_id,
            scenario_id,
            revision,
            principal.subject,
            _parse_if_match(if_match),
        )
        response.headers["ETag"] = _etag_header(view.etag)
        return view
    except ScenarioConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scenario-edit-conflict",
                "message": str(exc),
                "expected_etag": exc.expected_etag,
                "current_etag": exc.current_etag,
                "current_revision": exc.current_revision,
            },
        ) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/diagnostics",
    response_model=list[ScenarioGraphDiagnostic],
)
def get_scenario_diagnostics(
    simulation_id: str,
    scenario_id: str,
    _principal: ViewerPrincipal,
) -> list[ScenarioGraphDiagnostic]:
    try:
        return service.scenario_diagnostics(simulation_id, scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/state",
    response_model=ScenarioRuntimeState,
)
async def get_scenario_state(
    simulation_id: str, scenario_id: str, _principal: ViewerPrincipal
) -> ScenarioRuntimeState:
    try:
        return await service.scenario_state(simulation_id, scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"WireMock state inspection failed: {exc}"
        ) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/compile",
    response_model=ScenarioCompileResult,
)
def compile_scenario(
    simulation_id: str, scenario_id: str, _principal: OperatorPrincipal
) -> ScenarioCompileResult:
    try:
        return service.compile_scenario(simulation_id, scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/deploy",
    response_model=ScenarioDeployResult,
)
async def deploy_scenario(
    simulation_id: str, scenario_id: str, principal: OperatorPrincipal
) -> ScenarioDeployResult:
    try:
        return await service.deploy_scenario(simulation_id, scenario_id, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"WireMock scenario deployment failed: {exc}"
        ) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/{revision}/deploy",
    response_model=ScenarioDeployResult,
)
async def deploy_scenario_revision(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    principal: OperatorPrincipal,
) -> ScenarioDeployResult:
    try:
        return await service.deploy_scenario(
            simulation_id, scenario_id, actor=principal.subject, revision=revision
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scenario deployment failed: {exc}") from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/releases",
    response_model=list[ScenarioRelease],
)
def scenario_releases(
    simulation_id: str, scenario_id: str, _principal: ViewerPrincipal
) -> list[ScenarioRelease]:
    try:
        return service.scenario_releases(simulation_id, scenario_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/releases/{release_number}",
    response_model=ScenarioRelease,
)
def get_scenario_release(
    simulation_id: str,
    scenario_id: str,
    release_number: int,
    _principal: ViewerPrincipal,
) -> ScenarioRelease:
    try:
        return service.scenario_release(simulation_id, scenario_id, release_number)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/releases/{release_number}/rollback",
    response_model=ScenarioDeployResult,
)
async def rollback_scenario_release(
    simulation_id: str,
    scenario_id: str,
    release_number: int,
    principal: OperatorPrincipal,
) -> ScenarioDeployResult:
    try:
        return await service.rollback_scenario_release(
            simulation_id, scenario_id, release_number, principal.subject
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Scenario rollback failed: {exc}") from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/reset",
    response_model=ScenarioResetResult,
)
async def reset_scenario(
    simulation_id: str, scenario_id: str, _principal: OperatorPrincipal
) -> ScenarioResetResult:
    try:
        return await service.reset_scenario(simulation_id, scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"WireMock scenario reset failed: {exc}"
        ) from exc


@router.post("/scenarios/reset", response_model=ScenarioResetAllResult)
async def reset_all_scenarios(_principal: AdminPrincipal) -> ScenarioResetAllResult:
    try:
        return await service.reset_all_scenarios()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"WireMock scenario reset failed: {exc}"
        ) from exc


@router.get("/audit/events")
def audit_events(
    request: Request,
    _principal: AdminPrincipal,
    limit: int = Query(default=100, ge=1, le=1_000),
) -> dict:
    return {"events": request.app.state.audit_log.read_events(limit)}


@router.get("/audit/verify")
def verify_audit_log(request: Request, _principal: AdminPrincipal) -> dict:
    return request.app.state.audit_log.verify()
