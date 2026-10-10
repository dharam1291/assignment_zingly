import pytest

from zingly_core import IdentityLevel, TenantConfigStore, TenantContext, TenantNotFound

RAW = {
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
