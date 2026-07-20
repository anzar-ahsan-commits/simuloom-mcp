from simuloom.adapters.wiremock import WireMockClient
from simuloom.config import Settings
from simuloom.core.audit import AuditLog
from simuloom.core.repository import WorkspaceRepository
from simuloom.core.service import SimulationService
from simuloom.security import AccessController

settings = Settings.from_env()
access_controller = AccessController(settings.auth_enabled, settings.api_keys_json)
audit_log = AuditLog(settings.workspace / "audit" / "events.jsonl", settings.audit_signing_key)
service = SimulationService(
    repository=WorkspaceRepository(settings.workspace),
    wiremock=WireMockClient(settings.wiremock_url),
)
