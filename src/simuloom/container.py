from simuloom.adapters.native import NativeRuntimeAdapter
from simuloom.adapters.wiremock import WireMockClient
from simuloom.config import Settings
from simuloom.core.audit import AuditLog
from simuloom.core.repository import WorkspaceRepository
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
service = SimulationService(
    repository=WorkspaceRepository(settings.workspace),
    runtime=runtime,
)
