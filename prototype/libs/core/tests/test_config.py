import pytest

from zingly_core import IdentityLevel, TenantConfigStore, TenantContext, TenantNotFound

RAW = {
    "platform": {"mcp_url": "http://x"},
    "defaults": {"policy": {"lanes": {"parent_rps": 4, "P0": 0.4}}, "auth": {"max_attempts": 3}},
    "tenants": {
        "a": {"dialed_numbers": ["+1"], "policy": {"lanes": {"parent_rps": 8}}},
        "b": {"dialed_numbers": ["+2"]},
        "off": {"enabled": False},
    },
}


def test_sections_merge_defaults_per_tenant():
    store = TenantConfigStore(RAW)
    assert store.section("a", "policy")["lanes"] == {"parent_rps": 8, "P0": 0.4}
    assert store.section("b", "policy")["lanes"]["parent_rps"] == 4
    assert store.tenant_ids == ["a", "b"]


def test_resolve_by_dialed_number_and_unknown():
    store = TenantConfigStore(RAW)
    assert store.resolve(dialed_number="+2") == "b"
    with pytest.raises(TenantNotFound):
        store.resolve(dialed_number="+9")


def test_sections_are_copies():
    store = TenantConfigStore(RAW)
    store.section("a", "auth")["max_attempts"] = 99
    assert store.section("a", "auth")["max_attempts"] == 3


def test_context_keys_are_namespaced():
    assert TenantContext("a").key("alts", "LHR") == "a:alts:LHR"
    assert IdentityLevel.parse("verified") is IdentityLevel.VERIFIED


def test_identity_token_round_trip_and_tampering():
    import time

    from zingly_core import InvalidToken, identity_token as it

    key = it.signing_key("a")
    token = it.issue(key, "a", "conv-1", IdentityLevel.VERIFIED, "ABC123", ttl_s=60)
    claims = it.verify(key, token, "a")
    assert claims.level is IdentityLevel.VERIFIED and claims.booking_ref == "ABC123"
    for bad, tenant in [(token[:-1] + "0", "a"), (token, "b"), (it.issue(key, "a", "c", 2, None, -1), "a")]:
        with pytest.raises(InvalidToken):
            it.verify(key, bad, tenant)
    assert time.time() < claims.expires_at


def test_spans_nest_and_continue_across_processes():
    from zingly_core import tracing

    tracing.configure("test", sink_path="", memory=True)
    with tracing.span("outer", "gateway") as outer:
        with tracing.span("inner", "agents", agent="rebooking"):
            pass
        header = outer.traceparent
    with tracing.continue_trace(header):
        with tracing.span("remote", "mcp-server"):
            pass
    spans = {s["name"]: s for s in tracing.memory_spans()}
    assert spans["inner"]["parent_id"] == spans["outer"]["span_id"]
    assert spans["remote"]["parent_id"] == spans["outer"]["span_id"]
    assert len({s["trace_id"] for s in spans.values()}) == 1
