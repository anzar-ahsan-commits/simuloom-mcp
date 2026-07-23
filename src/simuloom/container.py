from simuloom.adapters.native import NativeRuntimeAdapter
from simuloom.adapters.wiremock import WireMockClient
from simuloom.config import Settings
from simuloom.core.ai_assistant import ScenarioAIAssistant
from simuloom.core.audit import AuditLog
from simuloom.core.integrations import IntegrationDispatcher
from simuloom.core.job_runner import JobRunner
from simuloom.core.metrics import MetricsRegistry
from simuloom.core.platform_store import PlatformStore
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.secrets import SecretVault
from simuloom.core.service import SimulationService
from simuloom.runtime.memory import MemoryRuntimeStore
from simuloom.runtime.sqlite import SQLiteRuntimeStore
from simuloom.security import AccessController

settings = Settings.from_env()
if settings.runtime == "native":
    runtime_store = (
        SQLiteRuntimeStore(settings.native_runtime_db, settings.native_journal_limit)
        if settings.native_runtime_store == "sqlite"
        else MemoryRuntimeStore(settings.native_journal_limit)
    )
    runtime = NativeRuntimeAdapter(settings.native_runtime_url, runtime_store)
else:
    runtime = WireMockClient(settings.wiremock_url)
access_controller = AccessController(settings.auth_enabled, settings.api_keys_json)
audit_log = AuditLog(settings.workspace / "audit" / "events.jsonl", settings.audit_signing_key)
platform_store = PlatformStore(settings.platform_db)
integration_dispatcher = IntegrationDispatcher(
    settings.integration_allowed_hosts,
    settings.integration_signing_key,
    settings.integration_allow_http,
    circuit_store=platform_store,
)
secret_vault = SecretVault(settings.secrets_master_key)
ai_assistant = ScenarioAIAssistant(
    settings.ai_enabled,
    settings.ai_base_url,
    settings.ai_model,
)
service = SimulationService(
    repository=WorkspaceRepository(settings.workspace),
    runtime=runtime,
    metrics=MetricsRegistry(platform_store),
)
job_runner = JobRunner(platform_store, service)
