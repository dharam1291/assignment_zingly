"""Shared base for every Zingly library.

Keep this package small: only what *every* module must agree on lives here - tenant context,
identity level and its signed assertion, tenant configuration, and trace context. A module's
own interfaces and default implementations belong in that module.
"""

from zingly_core import identity_token, tracing
from zingly_core.config import TenantConfigStore, TenantNotFound, deep_merge
from zingly_core.identity import IdentityLevel
from zingly_core.identity_token import IdentityClaims, InvalidToken
from zingly_core.tenancy import TenantContext

__all__ = ["IdentityLevel", "IdentityClaims", "InvalidToken", "TenantContext", "TenantConfigStore",
           "TenantNotFound", "deep_merge", "identity_token", "tracing"]
