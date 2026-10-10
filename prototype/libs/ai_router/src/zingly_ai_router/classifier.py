from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from zingly_ai_router.fast_path import normalise


@dataclass(frozen=True)
class Classification:
    domain: str | None
    confidence: float
    scores: dict[str, int] = field(default_factory=dict)


class IntentClassifier(Protocol):
    """The small classifier of design §3. LLM version: same signature, one small model call."""

    def classify(self, text: str) -> Classification: ...


class KeywordClassifier:
    def __init__(self, intents: Mapping[str, list[str]]):
        self._patterns = {domain: [re.compile(rf"\b{re.escape(normalise(k))}\b") for k in words]
                          for domain, words in intents.items()}

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "KeywordClassifier":
        return cls(section.get("intents", {}))

    def classify(self, text: str) -> Classification:
        norm = normalise(text)
        scores = {d: sum(1 for p in pats if p.search(norm)) for d, pats in self._patterns.items()}
        scores = {d: s for d, s in scores.items() if s}
        if not scores:
            return Classification(None, 0.0, {})
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_domain, top = ranked[0]
        confidence = top / sum(scores.values())
        return Classification(top_domain, round(confidence, 2), scores)
