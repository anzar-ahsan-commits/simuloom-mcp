import re
from typing import Annotated

import httpx
import yaml
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from simuloom.container import (
    ai_assistant,
    audit_log,
    integration_dispatcher,
    job_runner,
    platform_store,
    secret_vault,
    service,
)
from simuloom.core.gitops import build_snapshot
from simuloom.core.manifest import MAX_BUNDLE_SIZE
from simuloom.core.scenario_approvals import ScenarioApprovalError
from simuloom.core.scenario_revisions import ScenarioConflictError
from simuloom.models import (
    AIActionProposal,
    AIChatMessage,
    AIChatMessageCreate,
    AIChatThread,
    AIChatThreadCreate,
    AISettingsUpdate,
    AISettingsView,
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
    IntegrationCreate,
    IntegrationDelivery,
    IntegrationDispatch,
    IntegrationView,
    JobCreate,
    JobView,
    OperationSummary,
    ProfileConfigRequest,
    ProfileResult,
    ScenarioAIDraft,
    ScenarioAIDraftRequest,
    ScenarioClockAdvance,
    ScenarioClockView,
    ScenarioCompileResult,
    ScenarioDefinition,
    ScenarioDeployResult,
    ScenarioEventPublish,
    ScenarioEventResult,
    ScenarioGraphDiagnostic,
    ScenarioPromotionRequest,
    ScenarioPromotionResult,
    ScenarioRelease,
    ScenarioReleasePolicy,
    ScenarioReleasePolicyUpdate,
    ScenarioResetAllResult,
    ScenarioResetResult,
    ScenarioReview,
    ScenarioReviewDecision,
    ScenarioReviewRequest,
    ScenarioRevision,
    ScenarioRevisionComparison,
    ScenarioRevisionSummary,
    ScenarioRuntimeState,
    ScenarioSummary,
    ScenarioTemplate,
    ScenarioTemplateCreate,
    ScenarioTemplateInstantiate,
    ScenarioView,
    SecretMetadata,
    SecretPut,
    SessionView,
    Simulation,
    SimulationSummary,
    TeamWorkspace,
    TeamWorkspaceCreate,
    ValidationPlan,
    ValidationPlanRequest,
    ValidationRequest,
    WorkspaceMember,
    WorkspaceMemberUpdate,
    WorkspaceReadiness,
    WorkspaceRestoreResult,
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


def _ai_thread_for_principal(thread_id: str, principal: Principal) -> dict:
    try:
        thread = platform_store.get_ai_thread(thread_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if thread["owner"] != principal.subject and principal.role != Role.ADMIN:
        raise HTTPException(status_code=404, detail=f"AI conversation not found: {thread_id}")
    return thread


def _ai_simulation_context(simulation_id: str) -> dict:
    metadata = service.get(simulation_id)
    operations = [
        item.model_dump(mode="json") for item in service.contract_operations(simulation_id)
    ]
    scenarios = []
    for scenario_id, payload in service.repository.read_scenarios(simulation_id).items():
        definition = ScenarioDefinition.model_validate(payload)
        scenarios.append(
            {
                "id": scenario_id,
                "name": definition.name,
                "initial_state": definition.initial_state,
                "states": [state.name for state in definition.states],
                "transition_count": sum(
                    sum(handler.new_state is not None for handler in state.handlers)
                    + len(state.event_transitions)
                    for state in definition.states
                ),
            }
        )
    return {
        "simulation": {
            "id": simulation_id,
            "name": metadata["name"],
            "status": metadata["status"],
            "active_profile": metadata.get("activeProfile", "normal"),
        },
        "approved_operations": operations[:100],
        "scenarios": scenarios[:50],
        "safety": {
            "context_is_read_only": True,
            "actions_require_operator_approval": True,
        },
    }


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


@router.get("/readiness", response_model=WorkspaceReadiness)
async def readiness(_principal: ViewerPrincipal) -> WorkspaceReadiness:
    try:
        runtime_ready = await service.runtime.health()
    except Exception:
        runtime_ready = False
    workspace = service.repository.diagnostics()
    platform = platform_store.diagnostics()
    ready = runtime_ready and workspace["writable"] and platform["ready"]
    return WorkspaceReadiness(
        status="ready" if ready else "degraded",
        runtime=service.runtime.capabilities().runtime,
        runtime_ready=runtime_ready,
        workspace_format=workspace["format"],
        workspace_schema_version=workspace["schema_version"],
        supported_workspace_schema_version=workspace["supported_schema_version"],
        workspace_writable=workspace["writable"],
        simulation_count=workspace["simulation_count"],
        platform_store_ready=platform["ready"],
        platform_schema_version=platform["schema_version"],
        supported_platform_schema_version=platform["supported_schema_version"],
    )


@router.get("/readyz")
async def deployment_readiness(response: Response) -> dict[str, str]:
    try:
        runtime_ready = await service.runtime.health()
        platform_ready = platform_store.diagnostics()["ready"]
        workspace_ready = service.repository.diagnostics()["writable"]
    except Exception:
        runtime_ready = platform_ready = workspace_ready = False
    if not (runtime_ready and platform_ready and workspace_ready):
        response.status_code = 503
        return {"status": "not-ready"}
    return {"status": "ready"}


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(_principal: ViewerPrincipal) -> str:
    return service.prometheus_metrics()


@router.get("/metrics/json")
def metrics_snapshot(_principal: ViewerPrincipal) -> dict[str, int]:
    return service.metrics_snapshot()


@router.get("/diagnostics")
def operational_diagnostics(_principal: AdminPrincipal) -> dict[str, object]:
    return {
        "platform": platform_store.diagnostics(),
        "workspace": service.repository.diagnostics(),
        "audit": audit_log.verify(),
        "metrics": {
            "persistent": service.metrics.persistent,
            "counter_count": len(service.metrics_snapshot()),
        },
        "runtime": service.runtime.capabilities().model_dump(mode="json"),
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


def _require_workspace_admin(workspace_id: str, principal: Principal) -> None:
    if principal.role is Role.ADMIN:
        return
    if platform_store.membership_role(workspace_id, principal.subject) != "admin":
        raise HTTPException(status_code=403, detail="Workspace admin membership is required")


def _require_workspace_member(workspace_id: str, principal: Principal) -> None:
    if principal.role is Role.ADMIN:
        return
    if not platform_store.membership_role(workspace_id, principal.subject):
        raise HTTPException(status_code=403, detail="Workspace membership is required")


@router.post("/workspaces", response_model=TeamWorkspace, status_code=201)
def create_team_workspace(request: TeamWorkspaceCreate, principal: AdminPrincipal) -> TeamWorkspace:
    return TeamWorkspace.model_validate(
        platform_store.create_workspace(request.name, principal.subject)
    )


@router.get("/workspaces", response_model=list[TeamWorkspace])
def list_team_workspaces(principal: ViewerPrincipal) -> list[TeamWorkspace]:
    return [
        TeamWorkspace.model_validate(item)
        for item in platform_store.list_workspaces(
            principal.subject, include_all=principal.role is Role.ADMIN
        )
    ]


@router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMember])
def list_workspace_members(workspace_id: str, principal: ViewerPrincipal) -> list[WorkspaceMember]:
    if principal.role is not Role.ADMIN and not platform_store.membership_role(
        workspace_id, principal.subject
    ):
        raise HTTPException(status_code=403, detail="Workspace membership is required")
    try:
        return [
            WorkspaceMember.model_validate(item)
            for item in platform_store.list_members(workspace_id)
        ]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/workspaces/{workspace_id}/members/{subject}", response_model=WorkspaceMember)
def set_workspace_member(
    workspace_id: str,
    subject: str,
    request: WorkspaceMemberUpdate,
    principal: ViewerPrincipal,
) -> WorkspaceMember:
    _require_workspace_admin(workspace_id, principal)
    try:
        return WorkspaceMember.model_validate(
            platform_store.set_member(workspace_id, subject, request.role)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/workspaces/{workspace_id}/members/{subject}", status_code=204)
def remove_workspace_member(
    workspace_id: str, subject: str, principal: ViewerPrincipal
) -> Response:
    _require_workspace_admin(workspace_id, principal)
    try:
        platform_store.remove_member(workspace_id, subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post(
    "/workspaces/{workspace_id}/integrations", response_model=IntegrationView, status_code=201
)
def create_integration(
    workspace_id: str,
    request: IntegrationCreate,
    principal: ViewerPrincipal,
) -> IntegrationView:
    _require_workspace_admin(workspace_id, principal)
    try:
        endpoint = integration_dispatcher.validate_endpoint(request.endpoint)
        if request.secret_name:
            platform_store.secret_ciphertext(workspace_id, request.secret_name)
        return IntegrationView.model_validate(
            platform_store.create_integration(
                workspace_id,
                request.name,
                endpoint,
                request.event_types,
                request.secret_name,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_id}/integrations", response_model=list[IntegrationView])
def list_integrations(workspace_id: str, principal: ViewerPrincipal) -> list[IntegrationView]:
    _require_workspace_member(workspace_id, principal)
    try:
        return [
            IntegrationView.model_validate(item)
            for item in platform_store.list_integrations(workspace_id)
        ]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/workspaces/{workspace_id}/integrations/{integration_id}/dispatch",
    response_model=IntegrationDelivery,
)
async def dispatch_integration(
    workspace_id: str,
    integration_id: str,
    request: IntegrationDispatch,
    principal: OperatorPrincipal,
) -> IntegrationDelivery:
    _require_workspace_member(workspace_id, principal)
    try:
        integration = platform_store.get_integration(integration_id)
        if integration["workspace_id"] != workspace_id:
            raise KeyError(f"Integration not found: {integration_id}")
        signing_key = None
        if integration["secret_ref"]:
            signing_key = secret_vault.decrypt(
                platform_store.secret_ciphertext(workspace_id, integration["secret_ref"])
            )
        result = await integration_dispatcher.dispatch(
            integration, request.event_type, request.payload, signing_key
        )
        return IntegrationDelivery.model_validate(result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Integration delivery failed") from exc


@router.delete("/workspaces/{workspace_id}/integrations/{integration_id}", status_code=204)
def delete_integration(
    workspace_id: str, integration_id: str, principal: ViewerPrincipal
) -> Response:
    _require_workspace_admin(workspace_id, principal)
    try:
        integration = platform_store.get_integration(integration_id)
        if integration["workspace_id"] != workspace_id:
            raise KeyError(f"Integration not found: {integration_id}")
        platform_store.delete_integration(integration_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.put("/workspaces/{workspace_id}/secrets/{name}", response_model=SecretMetadata)
def put_workspace_secret(
    workspace_id: str,
    name: Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9_]{1,79}$")],
    request: SecretPut,
    principal: ViewerPrincipal,
) -> SecretMetadata:
    _require_workspace_admin(workspace_id, principal)
    if not secret_vault.available:
        raise HTTPException(status_code=503, detail="Workspace secret storage is not configured")
    try:
        ciphertext = secret_vault.encrypt(request.value)
        return SecretMetadata.model_validate(
            platform_store.put_secret(workspace_id, name, ciphertext)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_id}/secrets", response_model=list[SecretMetadata])
def list_workspace_secrets(workspace_id: str, principal: ViewerPrincipal) -> list[SecretMetadata]:
    _require_workspace_admin(workspace_id, principal)
    try:
        return [
            SecretMetadata.model_validate(item)
            for item in platform_store.list_secrets(workspace_id)
        ]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/workspaces/{workspace_id}/secrets/{name}", status_code=204)
def delete_workspace_secret(
    workspace_id: str,
    name: Annotated[str, Path(pattern=r"^[A-Z][A-Z0-9_]{1,79}$")],
    principal: ViewerPrincipal,
) -> Response:
    _require_workspace_admin(workspace_id, principal)
    try:
        platform_store.delete_secret(workspace_id, name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


def _execute_job(job_id: str, request: JobCreate) -> None:
    runner = (
        job_runner
        if job_runner.store is platform_store and job_runner.service is service
        else type(job_runner)(platform_store, service)
    )
    runner.execute_job(job_id)


@router.post("/jobs", response_model=JobView, status_code=202)
def create_job(
    request: JobCreate,
    background_tasks: BackgroundTasks,
    principal: OperatorPrincipal,
) -> JobView:
    _require_workspace_member(request.workspace_id, principal)
    try:
        job = platform_store.create_job(
            request.workspace_id,
            request.kind,
            {"simulation_id": request.simulation_id},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    background_tasks.add_task(_execute_job, job["id"], request)
    return JobView.model_validate(job)


@router.get("/workspaces/{workspace_id}/jobs", response_model=list[JobView])
def list_jobs(workspace_id: str, principal: ViewerPrincipal) -> list[JobView]:
    _require_workspace_member(workspace_id, principal)
    try:
        return [JobView.model_validate(item) for item in platform_store.list_jobs(workspace_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, principal: ViewerPrincipal) -> JobView:
    try:
        job = platform_store.get_job(job_id)
        _require_workspace_member(job["workspace_id"], principal)
        return JobView.model_validate(job)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@router.get("/simulations/{simulation_id}/gitops")
def simulation_gitops_snapshot(
    simulation_id: str, _principal: ViewerPrincipal
) -> dict[str, object]:
    try:
        return build_snapshot(service.repository, simulation_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/simulations/{simulation_id}/ai/scenarios/draft", response_model=ScenarioAIDraft)
async def draft_scenario_with_local_ai(
    simulation_id: str,
    request: ScenarioAIDraftRequest,
    _principal: OperatorPrincipal,
) -> ScenarioAIDraft:
    if not ai_assistant.enabled:
        raise HTTPException(status_code=503, detail="Local AI assistance is disabled")
    try:
        contract = service.repository.read_json(simulation_id, "contract.json")
        definition = await ai_assistant.draft(contract, request.intent, request.scenario_name)
        return ScenarioAIDraft(model=ai_assistant.model, definition=definition)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Local AI model request failed") from exc


@router.post("/ai/chat/threads", response_model=AIChatThread, status_code=201)
def create_ai_chat_thread(request: AIChatThreadCreate, principal: ViewerPrincipal) -> AIChatThread:
    try:
        service.get(request.simulation_id)
        return AIChatThread.model_validate(
            platform_store.create_ai_thread(request.simulation_id, request.title, principal.subject)
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ai/settings", response_model=AISettingsView)
def get_ai_settings(_principal: ViewerPrincipal) -> AISettingsView:
    return AISettingsView(
        enabled=ai_assistant.enabled,
        model=ai_assistant.model,
        base_url=ai_assistant.base_url,
        persisted=platform_store.get_setting("ai.enabled") is not None,
    )


@router.put("/ai/settings", response_model=AISettingsView)
def update_ai_settings(request: AISettingsUpdate, _principal: AdminPrincipal) -> AISettingsView:
    platform_store.set_setting("ai.enabled", "true" if request.enabled else "false")
    ai_assistant.enabled = request.enabled
    platform_store.increment_metric("ai_settings_changes_total")
    return get_ai_settings(_principal)


@router.get("/ai/chat/threads", response_model=list[AIChatThread])
def list_ai_chat_threads(principal: ViewerPrincipal) -> list[AIChatThread]:
    return [
        AIChatThread.model_validate(item)
        for item in platform_store.list_ai_threads(
            principal.subject, include_all=principal.role == Role.ADMIN
        )
    ]


@router.get("/ai/chat/threads/{thread_id}", response_model=AIChatThread)
def get_ai_chat_thread(thread_id: str, principal: ViewerPrincipal) -> AIChatThread:
    return AIChatThread.model_validate(_ai_thread_for_principal(thread_id, principal))


@router.post("/ai/chat/threads/{thread_id}/messages", response_model=AIChatMessage, status_code=201)
async def send_ai_chat_message(
    thread_id: str,
    request: AIChatMessageCreate,
    principal: ViewerPrincipal,
) -> AIChatMessage:
    if not ai_assistant.enabled:
        raise HTTPException(status_code=503, detail="Local AI assistance is disabled")
    thread = _ai_thread_for_principal(thread_id, principal)
    try:
        history = [AIChatMessage.model_validate(item) for item in thread["messages"]]
        context = _ai_simulation_context(thread["simulation_id"])
        platform_store.add_ai_message(thread_id, "user", request.content)
        completion = await ai_assistant.chat(context, history, request.content)
        stored = platform_store.add_ai_message(
            thread_id,
            "assistant",
            completion.answer,
            [
                item.model_dump(mode="json", exclude={"id", "status", "result"})
                for item in completion.actions
            ],
        )
        platform_store.increment_metric("ai_chat_messages_total")
        return AIChatMessage.model_validate(stored)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Local AI model request failed") from exc


@router.post("/ai/chat/actions/{action_id}/approve", response_model=AIActionProposal)
async def approve_ai_chat_action(action_id: str, principal: OperatorPrincipal) -> AIActionProposal:
    try:
        action = platform_store.get_ai_action(action_id)
        thread = _ai_thread_for_principal(action["thread_id"], principal)
        if action["status"] != "proposed":
            raise HTTPException(status_code=409, detail="AI action is no longer awaiting approval")
        claimed = platform_store.claim_ai_action(action_id)
        if claimed is None:
            raise HTTPException(status_code=409, detail="AI action is no longer awaiting approval")
        action = claimed
        arguments = action["arguments"]
        simulation_id = thread["simulation_id"]
        if action["kind"] == "generate_data":
            records = int(arguments.get("records", 25))
            seed = int(arguments.get("seed", 1207))
            if not 1 <= records <= 10_000:
                raise ValueError("AI-proposed record count must be between 1 and 10000")
            result = service.generate_data(simulation_id, records, seed).model_dump(mode="json")
        elif action["kind"] == "compile":
            result = service.compile(simulation_id).model_dump(mode="json")
        elif action["kind"] == "deploy":
            result = (await service.deploy(simulation_id, reset_existing=False)).model_dump(
                mode="json"
            )
        elif action["kind"] == "reset_scenario":
            scenario_id = str(arguments.get("scenario_id", ""))
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", scenario_id):
                raise ValueError("AI action requires a valid scenario_id")
            service.get_scenario(simulation_id, scenario_id)
            result = (await service.reset_scenario(simulation_id, scenario_id)).model_dump(
                mode="json"
            )
        else:
            raise ValueError("AI action kind is not allowlisted")
        updated = platform_store.update_ai_action(action_id, "executed", result)
        platform_store.increment_metric("ai_actions_executed_total")
        return AIActionProposal.model_validate(updated)
    except HTTPException:
        raise
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        try:
            platform_store.update_ai_action(action_id, "failed", {"error": str(exc)})
        except KeyError:
            pass
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        platform_store.update_ai_action(action_id, "failed", {"error": str(exc)})
        raise HTTPException(status_code=502, detail="Approved AI operation failed") from exc


@router.post("/ai/chat/actions/{action_id}/reject", response_model=AIActionProposal)
def reject_ai_chat_action(action_id: str, principal: OperatorPrincipal) -> AIActionProposal:
    try:
        action = platform_store.get_ai_action(action_id)
        _ai_thread_for_principal(action["thread_id"], principal)
        if action["status"] != "proposed":
            raise HTTPException(status_code=409, detail="AI action is no longer awaiting approval")
        return AIActionProposal.model_validate(
            platform_store.update_ai_action(action_id, "rejected")
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    except ScenarioApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/{revision}/promote",
    response_model=ScenarioPromotionResult,
)
def promote_scenario_revision(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    request: ScenarioPromotionRequest,
    principal: OperatorPrincipal,
) -> ScenarioPromotionResult:
    try:
        return service.promote_scenario_revision(
            simulation_id,
            scenario_id,
            revision,
            request.target_simulation_id,
            request.target_scenario_id,
            principal.subject,
            request.expected_target_etag,
        )
    except ScenarioConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/{revision}/template",
    response_model=ScenarioTemplate,
)
def create_scenario_template(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    request: ScenarioTemplateCreate,
    principal: OperatorPrincipal,
) -> ScenarioTemplate:
    try:
        return service.create_scenario_template(
            simulation_id,
            scenario_id,
            revision,
            request.template_id,
            request.name,
            request.description,
            principal.subject,
            request.parameterize,
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scenario-templates", response_model=list[ScenarioTemplate])
def list_scenario_templates(_principal: ViewerPrincipal) -> list[ScenarioTemplate]:
    return service.scenario_templates()


@router.get("/scenario-templates/{template_id}", response_model=ScenarioTemplate)
def get_scenario_template(template_id: str, _principal: ViewerPrincipal) -> ScenarioTemplate:
    try:
        return service.get_scenario_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/scenario-templates/{template_id}/instantiate", response_model=ScenarioView)
def instantiate_scenario_template(
    template_id: str,
    request: ScenarioTemplateInstantiate,
    principal: OperatorPrincipal,
) -> ScenarioView:
    try:
        return service.instantiate_scenario_template(
            template_id,
            request.simulation_id,
            request.scenario_id,
            principal.subject,
            request.expected_etag,
            request.parameters,
        )
    except ScenarioConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/release-policy",
    response_model=ScenarioReleasePolicy,
)
def get_scenario_release_policy(
    simulation_id: str, _principal: ViewerPrincipal
) -> ScenarioReleasePolicy:
    try:
        return service.scenario_release_policy(simulation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/simulations/{simulation_id}/release-policy",
    response_model=ScenarioReleasePolicy,
)
def update_scenario_release_policy(
    simulation_id: str,
    update: ScenarioReleasePolicyUpdate,
    principal: AdminPrincipal,
) -> ScenarioReleasePolicy:
    try:
        return service.update_scenario_release_policy(
            simulation_id,
            update.require_approval,
            update.block_breaking_changes,
            principal.subject,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/history/{revision}/review",
    response_model=ScenarioReview,
)
def request_scenario_review(
    simulation_id: str,
    scenario_id: str,
    revision: int,
    request: ScenarioReviewRequest,
    principal: OperatorPrincipal,
) -> ScenarioReview:
    try:
        return service.request_scenario_review(
            simulation_id, scenario_id, revision, principal.subject, request.note
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/reviews",
    response_model=list[ScenarioReview],
)
def scenario_reviews(
    simulation_id: str, scenario_id: str, _principal: ViewerPrincipal
) -> list[ScenarioReview]:
    try:
        return service.scenario_reviews(simulation_id, scenario_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _decide_scenario_review(
    simulation_id: str,
    scenario_id: str,
    review_number: int,
    approved: bool,
    decision: ScenarioReviewDecision,
    principal: Principal,
) -> ScenarioReview:
    try:
        return service.decide_scenario_review(
            simulation_id,
            scenario_id,
            review_number,
            approved,
            principal.subject,
            decision.note,
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/reviews/{review_number}/approve",
    response_model=ScenarioReview,
)
def approve_scenario_review(
    simulation_id: str,
    scenario_id: str,
    review_number: int,
    decision: ScenarioReviewDecision,
    principal: AdminPrincipal,
) -> ScenarioReview:
    return _decide_scenario_review(
        simulation_id, scenario_id, review_number, True, decision, principal
    )


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/reviews/{review_number}/reject",
    response_model=ScenarioReview,
)
def reject_scenario_review(
    simulation_id: str,
    scenario_id: str,
    review_number: int,
    decision: ScenarioReviewDecision,
    principal: AdminPrincipal,
) -> ScenarioReview:
    return _decide_scenario_review(
        simulation_id, scenario_id, review_number, False, decision, principal
    )


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
    except ScenarioApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except ScenarioApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.post(
    "/simulations/{simulation_id}/scenarios/{scenario_id}/clock/advance",
    response_model=ScenarioClockView,
)
async def advance_scenario_clock(
    simulation_id: str,
    scenario_id: str,
    request: ScenarioClockAdvance,
    principal: OperatorPrincipal,
) -> ScenarioClockView:
    try:
        return await service.advance_scenario_clock(
            simulation_id, scenario_id, request.milliseconds, principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/scenarios/reset", response_model=ScenarioResetAllResult)
async def reset_all_scenarios(_principal: AdminPrincipal) -> ScenarioResetAllResult:
    try:
        return await service.reset_all_scenarios()
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"WireMock scenario reset failed: {exc}"
        ) from exc


@router.post(
    "/simulations/{simulation_id}/events",
    response_model=ScenarioEventResult,
)
async def publish_scenario_event(
    simulation_id: str,
    event: ScenarioEventPublish,
    principal: OperatorPrincipal,
) -> ScenarioEventResult:
    try:
        return await service.publish_scenario_event(
            simulation_id, event.topic, event.payload, principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


@router.get("/audit/domain-events")
def domain_audit_events(
    _principal: AdminPrincipal,
    limit: int = Query(default=100, ge=1, le=1_000),
) -> dict:
    return {"events": service.domain_audit_events(limit)}


@router.get("/audit/domain-verify")
def verify_domain_audit(_principal: AdminPrincipal) -> dict:
    return service.verify_domain_audit()


@router.get("/workspace/backup")
def workspace_backup(_principal: AdminPrincipal) -> Response:
    data = service.workspace_backup()
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="simuloom-workspace.zip"'},
    )


@router.post("/workspace/restore", response_model=WorkspaceRestoreResult)
async def restore_workspace(
    backup: Annotated[UploadFile, File()], principal: AdminPrincipal
) -> WorkspaceRestoreResult:
    from simuloom.core.workspace_backup import MAX_WORKSPACE_BACKUP_SIZE

    data = await backup.read(MAX_WORKSPACE_BACKUP_SIZE + 1)
    try:
        return service.restore_workspace(data, principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
