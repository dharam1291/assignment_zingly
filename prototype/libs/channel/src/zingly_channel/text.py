from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class Utterance:
    text: str
    kind: str = "speech"      # speech | dtmf
    confidence: float = 1.0   # STT confidence; always 1.0 for typed text


@dataclass(frozen=True)
class Outbound:
    text: str
    interruptible: bool = True  # AI disclosure and itinerary read-back are not (design §3)


@dataclass
class ChannelConfig:
    max_input_chars: int = 500
    dtmf_enabled: bool = True

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "ChannelConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


class Channel(Protocol):
    name: str

    def inbound(self, raw: Mapping[str, Any]) -> Utterance: ...

    def outbound(self, message: Outbound) -> dict: ...


class TextChannel:
    name = "text"

    def __init__(self, config: ChannelConfig):
        self.config = config

    def inbound(self, raw: Mapping[str, Any]) -> Utterance:
        if self.config.dtmf_enabled and raw.get("dtmf"):
            digits = re.sub(r"[^0-9*#]", "", str(raw["dtmf"]))
            return Utterance(digits, kind="dtmf")
        text = re.sub(r"\s+", " ", str(raw.get("text", ""))).strip()
        return Utterance(text[: self.config.max_input_chars])

    def outbound(self, message: Outbound) -> dict:
        return {"text": message.text, "interruptible": message.interruptible, "channel": self.name}
