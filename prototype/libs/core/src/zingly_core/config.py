"""One configuration file, many tenants, one deployment.

File layout (TOML)::

    [defaults.<module>]          # applies to every tenant
    [tenants.<id>]               # tenant identity and routing keys
    dialed_numbers = ["+44..."]
    [tenants.<id>.<module>]      # overrides for that tenant only

Each module receives only its own merged section via :meth:`TenantConfigStore.section`.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any, Mapping

_RESERVED = {"display_name", "dialed_numbers", "enabled"}


class TenantNotFound(KeyError):
    pass


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


class TenantConfigStore:
    def __init__(self, raw: Mapping[str, Any]):
        defaults = raw.get("defaults", {})
        tenants = raw.get("tenants", {})
        if not tenants:
            raise ValueError("config has no [tenants.*] blocks")
        self._tenants: dict[str, dict[str, Any]] = {}
        self._by_number: dict[str, str] = {}
        for tenant_id, block in tenants.items():
            if not block.get("enabled", True):
                continue
            modules = {k: v for k, v in block.items() if k not in _RESERVED}
            merged = deep_merge(defaults, modules)
            merged["_meta"] = {
                "tenant_id": tenant_id,
                "display_name": block.get("display_name", tenant_id),
                "dialed_numbers": list(block.get("dialed_numbers", [])),
            }
            self._tenants[tenant_id] = merged
            for number in block.get("dialed_numbers", []):
                if number in self._by_number:
                    raise ValueError(f"dialed number {number} mapped to two tenants")
                self._by_number[number] = tenant_id

    @classmethod
    def from_file(cls, path: str | Path) -> "TenantConfigStore":
        with open(path, "rb") as fh:
            return cls(tomllib.load(fh))

    @property
    def tenant_ids(self) -> list[str]:
        return sorted(self._tenants)

    def resolve(self, *, tenant_id: str | None = None, dialed_number: str | None = None) -> str:
        if tenant_id:
            if tenant_id not in self._tenants:
                raise TenantNotFound(tenant_id)
            return tenant_id
        if dialed_number and dialed_number in self._by_number:
            return self._by_number[dialed_number]
        raise TenantNotFound(dialed_number or "<none>")

    def section(self, tenant_id: str, module: str) -> dict[str, Any]:
        if tenant_id not in self._tenants:
            raise TenantNotFound(tenant_id)
        return copy.deepcopy(self._tenants[tenant_id].get(module, {}))

    def meta(self, tenant_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._tenants[tenant_id]["_meta"])
