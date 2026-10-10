"""Shared base for every Zingly library.

Keep this package small: only types that *every* module must agree on live here
(tenant context, identity level, tenant configuration). A module's own interfaces
and default implementations belong in that module.
"""

from zingly_core.identity import IdentityLevel
from zingly_core.tenancy import TenantContext
from zingly_core.config import TenantConfigStore, TenantNotFound, deep_merge

__all__ = ["IdentityLevel", "TenantContext", "TenantConfigStore", "TenantNotFound", "deep_merge"]
