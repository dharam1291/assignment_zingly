from zingly_core import IdentityLevel, TenantContext
from zingly_handover import AttemptedAction, GenesysHandoverBuilder, HandoverConfig, HandoverRequest


def test_payload_carries_who_why_and_what_was_tried_with_masking():
    builder = GenesysHandoverBuilder(HandoverConfig(queues={"rebooking": "Disruption_Rebooking"}))
    req = HandoverRequest(
        ctx=TenantContext("atlantica", "conv-1", "call-1"), category="rebooking", subcategory="rebook_failed",
        reason="rebooking could not be completed", identity_level=IdentityLevel.VERIFIED,
        caller_number="+447700900001", verified_by="booking_ref+surname",
        booking={"ref": "ABC123", "flight": "AT123", "cabin": "economy", "surname": "Smith"},
        disruption={"flight": "AT123", "status": "CANCELLED", "reason": "weather"},
        attempted_actions=[AttemptedAction("rebook", "failed", "reservation timeout, booking unchanged",
                                           {"to_flight": "AT127"})])
    p = builder.build(req)
    assert p["conversation_status"] == "AGENT_HANDOVER"
    assert p["routing"]["queue"] == "Disruption_Rebooking"
    assert p["booking"]["ref_masked"] == "A***23" and "surname" not in p["booking"]
    assert "ABC123" not in str(p) and "+447700900001" not in str(p)
    assert "rebook AT127 -> failed (reservation timeout, booking unchanged)" in p["summary"]
    assert all(isinstance(v, str) for v in p["genesys_participant_data"].values())
