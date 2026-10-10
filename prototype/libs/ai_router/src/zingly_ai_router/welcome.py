from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass
class WelcomeConfig:
    text: str = "Hello, you're through to the airline's virtual assistant."
    consent_required: bool = True
    consent_prompt: str = "I'm an AI assistant and this call may be recorded. Is that OK?"
    after_consent: str = "Thanks. How can I help with your flight today?"
    consent_declined: str = "No problem. I'll connect you to a colleague."
    audio_version: str = "v1"

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "WelcomeConfig":
        known = {k: section[k] for k in cls.__dataclass_fields__ if k in section}
        return cls(**known)


class Welcome:
    """Welcome and consent are fixed per tenant, so their audio is pre-rendered and cached:
    no TTS call at call start. ``audio_id`` is the cache key the voice worker would play."""

    def __init__(self, config: WelcomeConfig):
        self.config = config

    def opening(self, tenant_id: str) -> tuple[str, str]:
        c = self.config
        text = f"{c.text} {c.consent_prompt if c.consent_required else c.after_consent}"
        return text, f"{tenant_id}:welcome:{c.audio_version}"
