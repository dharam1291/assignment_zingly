"""Deterministic slot extraction (what the LLM would do in normal mode)."""

from __future__ import annotations

import re
import time

_ORDINALS = {"1": 0, "one": 0, "first": 0, "earlier": 0, "earliest": 0,
             "2": 1, "two": 1, "second": 1, "later": 1, "latest": 1, "3": 2, "three": 2, "third": 2}
_NONE = ("neither", "none", "no thanks", "not those", "something else")


def booking_ref(text: str) -> str | None:
    upper = text.upper()
    for token in re.findall(r"[A-Z0-9]{6}", re.sub(r"[^A-Z0-9 ]", " ", upper)):
        if re.search(r"\d", token):
            return token
    compact = re.sub(r"[^A-Z0-9]", "", upper)  # "A B C 1 2 3"
    if len(compact) == 6 and re.search(r"\d", compact):
        return compact
    return None


def surname(text: str) -> str | None:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", text)
    return words[-1] if words else None


def flight_number(text: str) -> str | None:
    m = re.search(r"\b([A-Za-z]{2})\s?(\d{2,4})\b", text)
    return (m.group(1) + m.group(2)).upper() if m else None


def choice(text: str, options: list[dict]) -> int | None | str:
    low = text.lower()
    if any(p in low for p in _NONE):
        return "none"
    for i, opt in enumerate(options):
        if opt["flight"].lower() in low.replace(" ", "") or opt["departure"] in low:
            return i
    for word in re.findall(r"[a-z0-9]+", low):
        idx = _ORDINALS.get(word)
        if idx is not None and idx < len(options):
            return idx
    return None


def hhmm(epoch: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(epoch or time.time()))
