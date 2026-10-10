from zingly_ai_router import AIRouter, BusinessRouter, RouterState, RoutingConfig
from zingly_core import TenantContext

CFG = {
    "welcome": {"text": "Welcome to Atlantica.", "consent_required": True},
    "intents": {"rebooking": ["cancelled", "rebook", "options"], "flight_status": ["status", "delayed"],
                "faq": ["baggage", "bag", "hotel"]},
    "routing": {"enabled_agents": ["rebooking", "flight_status", "faq"]},
}
CTX = TenantContext("atlantica", "conv-1")


def consented():
    router, state = AIRouter.from_config(CFG), RouterState()
    router.start(CTX, state)
    assert router.route(CTX, state, "yes").kind == "say"
    return router, state


def test_welcome_is_a_cached_phrase_and_consent_comes_first():
    router, state = AIRouter.from_config(CFG), RouterState()
    text, audio_id = router.start(CTX, state)
    assert audio_id == "atlantica:welcome:v1" and "Is that OK?" in text
    d = router.route(CTX, state, "my flight was cancelled")
    assert d.kind == "say" and "Is that OK?" in d.text  # no dispatch before consent


def test_hi_is_fast_path_but_hi_plus_intent_is_not():
    router, state = consented()
    assert router.route(CTX, state, "Hi!").path == "fast_path"
    d = router.route(CTX, state, "Hi, my flight was cancelled")
    assert (d.kind, d.agent, d.path) == ("dispatch", "rebooking", "topic_change")


def test_slot_answers_stay_on_topic_and_yes_goes_to_pending_question():
    router, state = consented()
    router.route(CTX, state, "my flight was cancelled")
    state.pending_question = "booking_ref"
    assert router.route(CTX, state, "A B C 1 2 3").agent == "rebooking"
    state.pending_question = "confirm_rebook"
    d = router.route(CTX, state, "yes please")
    assert (d.agent, d.yes_no, d.path) == ("rebooking", "yes", "fast_path")


def test_topic_change_and_ambiguity():
    router, state = consented()
    router.route(CTX, state, "what are my options")
    assert router.route(CTX, state, "where is my bag").agent == "faq"
    router2, state2 = consented()
    d = router2.route(CTX, state2, "the cancelled flight and the hotel")   # two domains, tie
    assert d.path == "clarify"


def test_agent_request_and_disabled_agent_hand_over():
    router, state = consented()
    assert router.route(CTX, state, "can I talk to a real person").kind == "handover"
    cfg = {**CFG, "routing": {"enabled_agents": ["faq"]}}
    router, state = AIRouter.from_config(cfg), RouterState(consent=True)
    d = router.route(CTX, state, "my flight was cancelled")
    assert (d.kind, d.category, d.subcategory) == ("handover", "rebooking", "agent_disabled")


def test_rollout_percent_is_stable_per_conversation():
    br = BusinessRouter(RoutingConfig(rollout_percent={"rebooking": 30}))
    admitted = [br.admit(TenantContext("t", f"c{i}"), "rebooking").allowed for i in range(1000)]
    assert 250 < sum(admitted) < 350
    assert br.admit(TenantContext("t", "c7"), "rebooking") == br.admit(TenantContext("t", "c7"), "rebooking")
