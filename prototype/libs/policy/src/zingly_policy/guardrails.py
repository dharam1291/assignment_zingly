from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from zingly_core import IdentityLevel


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str = ""


class ToolGuard(Protocol):
    def check(self, tool: str, level: IdentityLevel) -> GuardDecision: ...


@dataclass
class LevelGuard:
    """Allow-list: a tool runs only if the caller's level reaches its minimum.

    Tools not listed are denied, so a new tool is closed until a tenant opens it.
    """

    min_level: dict[str, IdentityLevel] = field(default_factory=dict)

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> "LevelGuard":
        raw = section.get("tool_min_level", {})
        return cls({tool: IdentityLevel.parse(level) for tool, level in raw.items()})

    def check(self, tool: str, level: IdentityLevel) -> GuardDecision:
        required = self.min_level.get(tool)
        if required is None:
            return GuardDecision(False, f"tool '{tool}' is not allow-listed for this tenant")
        if level < required:
            return GuardDecision(False, f"'{tool}' needs {required.label}, caller is {level.label}")
        return GuardDecision(True)
