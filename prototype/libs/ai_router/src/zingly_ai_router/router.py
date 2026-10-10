from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from zingly_core import TenantContext

from zingly_ai_router.business_routing import BusinessRouter, RoutingConfig
from zingly_ai_router.classifier import IntentClassifier, KeywordClassifier
from zingly_ai_router.fast_path import FastPath, FastPathConfig
from zingly_ai_router.welcome import Welcome, WelcomeConfig


@dataclass
class RouterState:
    """The router's slice of a conversation. The service stores it; the router owns its shape."""

    consent: bool | None = None
    active_domain: str | None = None
    pending_question: str | None = None   # set from the agent's reply, e.g. "confirm_rebook"
    clarify_count: int = 0
    consent_reprompts: int = 0


@dataclass
class RouteDecision:
    kind: str                          # say | dispatch | handover | end
    path: str                          # fast_path | same_topic | topic_change | clarify
    text: str = ""
    agent: str | None = None
    yes_no: str | None = None
    category: str = ""
    subcategory: str = ""
    reason: str = ""


@dataclass
class RouterConfig:
    min_confidence: float = 0.6
    switch_confidence: float = 0.75
    max_clarify: int = 2
    clarify_prompt: str = ("Is this about a cancelled or changed flight, a flight's status, "
                           "or something else, like baggage?")
    unclear_reply: str = "Sorry, I didn't catch that. What can I help you with?"
    goodbye_reply: str = "Thanks for calling. Goodbye."

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "RouterConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


class AIRouter:
    def __init__(self, config: RouterConfig, welcome: Welcome, fast_path: FastPath,
                 classifier: IntentClassifier, business: BusinessRouter):
        self.config = config
        self.welcome = welcome
        self.fast_path = fast_path
        self.classifier = classifier
        self.business = business

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "AIRouter":
        return cls(RouterConfig.from_config(section.get("disambiguation", {})),
                   Welcome(WelcomeConfig.from_config(section.get("welcome", {}))),
                   FastPath(FastPathConfig.from_config(section.get("fast_path", {}))),
                   KeywordClassifier.from_config(section),
                   BusinessRouter(RoutingConfig.from_config(section.get("routing", {}))))

    def start(self, ctx: TenantContext, state: RouterState) -> tuple[str, str]:
        if not self.welcome.config.consent_required:
            state.consent = True
        return self.welcome.opening(ctx.tenant_id)

    def route(self, ctx: TenantContext, state: RouterState, text: str) -> RouteDecision:
        fp = self.fast_path.match(text)

        if fp and fp.kind == "agent":
            return self._handover(state.active_domain or "general", "caller_requested_agent",
                                  "caller asked for a person")

        if state.consent is None:
            if fp and fp.kind == "yes":
                state.consent = True
                return RouteDecision("say", "fast_path", self.welcome.config.after_consent)
            if fp and fp.kind == "no":
                state.consent = False
                return self._handover("general", "consent_declined", "caller declined AI assistance",
                                      text=self.welcome.config.consent_declined)
            state.consent_reprompts += 1
            if state.consent_reprompts > 1:
                return self._handover("general", "consent_unclear", "no clear answer to consent")
            return RouteDecision("say", "fast_path", self.welcome.config.consent_prompt)

        if fp and fp.kind in ("yes", "no"):
            if state.active_domain and state.pending_question:
                return RouteDecision("dispatch", "fast_path", agent=state.active_domain, yes_no=fp.kind)
            if fp.kind == "no":
                return RouteDecision("end", "fast_path", self.config.goodbye_reply)
            return RouteDecision("say", "fast_path", self.fast_path.config.greeting_reply)
        if fp and fp.kind == "greeting":
            return RouteDecision("say", "fast_path", self.fast_path.config.greeting_reply)
        if fp and fp.kind == "goodbye":
            return RouteDecision("end", "fast_path", self.config.goodbye_reply)

        result = self.classifier.classify(text)
        active = state.active_domain
        if active:
            # Same-topic is the default, so slot answers like "ABC123" never trigger a switch.
            switching = (result.domain and result.domain != active
                         and result.confidence >= self.config.switch_confidence)
            if not switching:
                return RouteDecision("dispatch", "same_topic", agent=active)
            return self._enter(ctx, state, result.domain, "topic_change")

        if result.domain and result.confidence >= self.config.min_confidence:
            return self._enter(ctx, state, result.domain, "topic_change")

        state.clarify_count += 1
        if state.clarify_count > self.config.max_clarify:
            return self._handover("general", "unclear_intent", "intent still unclear after clarifying")
        return RouteDecision("say", "clarify", self.config.clarify_prompt)

    def _enter(self, ctx: TenantContext, state: RouterState, domain: str, path: str) -> RouteDecision:
        verdict = self.business.admit(ctx, domain)
        if not verdict.allowed:
            return self._handover(domain, verdict.reason, f"{domain} agent not available for this call")
        state.active_domain = domain
        state.pending_question = None
        state.clarify_count = 0
        return RouteDecision("dispatch", path, agent=domain)

    @staticmethod
    def _handover(category: str, subcategory: str, reason: str, text: str = "") -> RouteDecision:
        return RouteDecision("handover", "fast_path", text, category=category, subcategory=subcategory,
                             reason=reason)
