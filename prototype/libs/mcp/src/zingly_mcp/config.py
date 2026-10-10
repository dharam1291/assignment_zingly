from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class McpConfig:
    pss_base_url: str = "http://127.0.0.1:9001"
    airline_code: str = "atlantica"
    timeout_s: float = 2.0
    status_ttl_s: float = 60.0
    alternatives_ttl_s: float = 25.0
    booking_ttl_s: float = 600.0
    deferred_commit: bool = True
    prewarm_wait_s: float = 10.0
    protection_enabled: bool = True  # demo switch: False sends every call straight to the PSS

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "McpConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)
