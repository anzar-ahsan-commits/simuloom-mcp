from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from simuloom.container import service
from simuloom.core.manifest import MAX_BUNDLE_SIZE
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
    ProfileConfigRequest,
    ProfileResult,
    Simulation,
    ValidationPlan,
    ValidationPlanRequest,
    ValidationRequest,
)
from simuloom.security import Principal, Role, require_role, role_allows

router = APIRouter(prefix="/api/v1")
ViewerPrincipal = Annotated[Principal, Depends(require_role(Role.VIEWER))]
OperatorPrincipal = Annotated[Principal, Depends(require_role(Role.OPERATOR))]
AdminPrincipal = Annotated[Principal, Depends(require_role(Role.ADMIN))]


@router.get("/health")
async def health() -> dict[str, str | bool]:
    try:
        wiremock_ready = await service.wiremock.health()
    except Exception:
        wiremock_ready = False
    return {"status": "ok", "wiremockReady": wiremock_ready}


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


@router.get("/simulations/{simulation_id}")
def get_simulation(simulation_id: str, _principal: ViewerPrincipal) -> dict:
    try:
        return service.get(simulation_id)
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
        return await service.deploy(simulation_id, request.reset_existing)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WireMock deployment failed: {exc}") from exc


@router.post("/simulations/{simulation_id}/validate", response_model=EvidenceReport)
async def validate_simulation(
    simulation_id: str, request: ValidationRequest, _principal: OperatorPrincipal
) -> EvidenceReport:
    try:
        return await service.validate(
            simulation_id, request.max_dataset_cases, request.reset_runtime_state
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
        return service.plan_validation(simulation_id, request.max_dataset_cases)
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
