"""Auth service (design §4): identity is a level, issued here and never by a model.

Verify on demand: a caller-ID match gives LIKELY for free; booking reference + surname gives
VERIFIED. Three failures lock self-service for the caller's number. A failure never says
whether the booking reference exists.
"""

from zingly_auth.service import AuthConfig, AuthResult, AuthService, BookingLookupPort, DefaultAuthService, mask_ref

__all__ = ["AuthConfig", "AuthResult", "AuthService", "BookingLookupPort", "DefaultAuthService", "mask_ref"]
