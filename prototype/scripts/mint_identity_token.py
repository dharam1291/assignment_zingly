"""Mint a signed identity token for testing the MCP server from Codex, the Inspector or curl.

In the real flow only the Auth service issues these, after verifying the caller. This uses
the same per-tenant key (ZINGLY_IDENTITY_KEY_<TENANT>, or the dev key when unset).

    python scripts/mint_identity_token.py --tenant atlantica --booking ABC123
    export ZINGLY_IDENTITY_TOKEN=$(python scripts/mint_identity_token.py --booking ABC123)
"""

from __future__ import annotations

import argparse

from zingly_core import IdentityLevel, identity_token


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tenant", default="atlantica")
    p.add_argument("--booking", required=True, help="booking reference the token is scoped to")
    p.add_argument("--level", default="verified", choices=["unknown", "likely", "verified", "strongly_verified"])
    p.add_argument("--ttl", type=int, default=3600)
    args = p.parse_args()
    key = identity_token.signing_key(args.tenant)
    print(identity_token.issue(key, args.tenant, "manual-test", IdentityLevel.parse(args.level),
                               args.booking.upper(), args.ttl))


if __name__ == "__main__":
    main()
