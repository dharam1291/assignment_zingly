"""AI router (design §2 step 5, §3): welcome, consent, fast path, disambiguation and
business routing. Decides *who* handles a turn; never answers a domain question itself.

Turn paths (design §3 table)::

    fast_path     greeting / yes-no / keypad / "agent"      0 LLM calls
    same_topic    the active domain agent continues        1 LLM call  (in LLM mode)
    topic_change  classifier picks a new domain agent      1 small + 1
    clarify       intent unclear: one short question       1 small

This default implementation runs in the design's deterministic mode (§7): a keyword
classifier stands in for the small LLM classifier behind the same interface.
"""

from zingly_ai_router.business_routing import BusinessRouter, RoutingConfig
from zingly_ai_router.classifier import Classification, IntentClassifier, KeywordClassifier
from zingly_ai_router.fast_path import FastPath, FastPathConfig, FastPathMatch, normalise
from zingly_ai_router.router import AIRouter, RouteDecision, RouterConfig, RouterState
from zingly_ai_router.welcome import Welcome, WelcomeConfig

__all__ = [
    "BusinessRouter", "RoutingConfig", "Classification", "IntentClassifier", "KeywordClassifier",
    "FastPath", "FastPathConfig", "FastPathMatch", "normalise", "AIRouter", "RouteDecision", "RouterConfig",
    "RouterState", "Welcome", "WelcomeConfig",
]
