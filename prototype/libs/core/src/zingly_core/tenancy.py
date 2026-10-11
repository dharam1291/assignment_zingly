from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    """Travels with every call into every module, so all state can be tenant-scoped."""

    tenant_id: str
    conversation_id: str = ""
    call_id: str = ""

    def key(self, *parts: object) -> str:
        """Namespaced key, e.g. ``atlantica:alts:LHR:BOS``. Keeps tenants isolated."""
        return ":".join([self.tenant_id, *(str(p) for p in parts)])
