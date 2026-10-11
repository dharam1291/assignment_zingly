"""Exact-match rules on the whole normalised utterance. No model, so it can never guess:
"Hi, my flight was cancelled" does not match a greeting and goes on to the agents."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

_FILLERS = {"um", "uh", "er", "erm", "hmm", "oh", "well", "please"}


def normalise(text: str) -> str:
    text = re.sub(r"[^\w\s']", " ", text.lower())
    return " ".join(w for w in text.split() if w not in _FILLERS)


@dataclass
class FastPathConfig:
    greetings: list[str] = field(default_factory=lambda: ["hi", "hello", "hey", "good morning", "good afternoon"])
    yes: list[str] = field(default_factory=lambda: ["yes", "yeah", "yep", "sure", "ok", "okay", "correct",
                                                    "that's right", "yes please", "go ahead"])
    no: list[str] = field(default_factory=lambda: ["no", "nope", "no thanks", "no thank you"])
    agent_phrases: list[str] = field(default_factory=lambda: ["agent", "human", "person", "representative",
                                                              "operator", "speak to someone", "real person"])
    goodbye: list[str] = field(default_factory=lambda: ["bye", "goodbye", "that's all", "nothing else",
                                                        "no that's all", "thanks bye", "thank you bye"])
    greeting_reply: str = "How can I help with your flight today?"

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "FastPathConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


@dataclass(frozen=True)
class FastPathMatch:
    kind: str  # greeting | yes | no | agent | goodbye


class FastPath:
    def __init__(self, config: FastPathConfig):
        self.config = config
        c = config
        self._exact = {**{p: "greeting" for p in c.greetings}, **{p: "goodbye" for p in c.goodbye},
                       **{p: "yes" for p in c.yes}, **{p: "no" for p in c.no}}
        self._agent = [normalise(p) for p in c.agent_phrases]

    def match(self, text: str) -> FastPathMatch | None:
        norm = normalise(text)
        if not norm:
            return None
        if any(re.search(rf"\b{re.escape(p)}\b", norm) for p in self._agent):
            return FastPathMatch("agent")  # asking for a person is honoured mid-sentence too
        kind = self._exact.get(norm)
        return FastPathMatch(kind) if kind else None
