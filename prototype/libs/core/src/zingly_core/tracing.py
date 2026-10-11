"""Minimal distributed tracing, W3C ``traceparent`` compatible.

Every process writes finished spans as JSON lines to one sink (``ZINGLY_TRACE_FILE``), which
plays the role of a local trace collector. Context crosses process boundaries in the
``traceparent`` HTTP header (or MCP ``_meta.traceparent``). In production the same span
names and attributes map one to one onto OpenTelemetry spans exported over OTLP.

Never put PII in attributes: mask references, numbers and names before recording.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

_current: contextvars.ContextVar["Span | None"] = contextvars.ContextVar("zingly_span", default=None)
_remote: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar("zingly_remote", default=None)
_lock = threading.Lock()
_service = os.environ.get("ZINGLY_SERVICE", "unknown")
_sink_path: str | None = os.environ.get("ZINGLY_TRACE_FILE") or None
_memory: list[dict] | None = None


def configure(service: str, sink_path: str | None = None, memory: bool = False) -> None:
    global _service, _sink_path, _memory
    _service = service
    if sink_path is not None:
        _sink_path = sink_path or None
    if memory:
        _memory = []


def memory_spans() -> list[dict]:
    return list(_memory or [])


@dataclass
class Span:
    name: str
    component: str
    trace_id: str
    span_id: str
    parent_id: str | None
    attrs: dict[str, Any] = field(default_factory=dict)
    start: float = field(default_factory=time.time)
    status: str = "ok"

    def set(self, **attrs: Any) -> "Span":
        self.attrs.update({k: v for k, v in attrs.items() if v is not None})
        return self

    @property
    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-01"


def _export(span: Span, end: float) -> None:
    record = {"trace_id": span.trace_id, "span_id": span.span_id, "parent_id": span.parent_id,
              "service": _service, "component": span.component, "name": span.name,
              "start": round(span.start, 6), "duration_ms": round((end - span.start) * 1000, 2),
              "status": span.status, "attrs": span.attrs}
    line = json.dumps(record, default=str)
    with _lock:
        if _memory is not None:
            _memory.append(record)
        if _sink_path:
            os.makedirs(os.path.dirname(_sink_path) or ".", exist_ok=True)
            with open(_sink_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")


def parse_traceparent(value: str | None) -> tuple[str, str] | None:
    try:
        version, trace_id, span_id, _flags = (value or "").split("-")
        if len(trace_id) == 32 and len(span_id) == 16:
            return trace_id, span_id
    except ValueError:
        pass
    return None


@contextlib.contextmanager
def continue_trace(traceparent: str | None) -> Iterator[None]:
    """Make the next span a child of a span in another process."""
    token = _remote.set(parse_traceparent(traceparent))
    try:
        yield
    finally:
        _remote.reset(token)


@contextlib.contextmanager
def span(name: str, component: str, **attrs: Any) -> Iterator[Span]:
    parent = _current.get()
    if parent is not None:
        trace_id, parent_id = parent.trace_id, parent.span_id
    elif (remote := _remote.get()) is not None:
        trace_id, parent_id = remote
    else:
        trace_id, parent_id = secrets.token_hex(16), None
    s = Span(name, component, trace_id, secrets.token_hex(8), parent_id)
    s.set(**attrs)
    token = _current.set(s)
    try:
        yield s
    except BaseException as exc:
        s.status = "error"
        s.attrs.setdefault("error", type(exc).__name__)
        raise
    finally:
        _current.reset(token)
        _export(s, time.time())


def current() -> Span | None:
    return _current.get()


def current_traceparent() -> str | None:
    s = _current.get()
    return s.traceparent if s else None


def mask(value: str | None, keep: int = 2) -> str:
    if not value:
        return ""
    return "*" * max(0, len(value) - keep) + value[-keep:]


def read_spans(path: str, trace_id: str | None = None) -> list[dict]:
    """Spans from a collector file, optionally only one trace."""
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if trace_id and trace_id not in line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if trace_id is None or rec["trace_id"] == trace_id:
                out.append(rec)
    return out


_SKIP_ATTRS = {"tenant", "conversation_id", "endpoint"}


def render_tree(spans: list[dict], show_attrs: bool = True) -> str:
    """Indented span tree: ``service / component  name  duration  key=value``."""
    by_parent: dict[str | None, list[dict]] = {}
    ids = {s["span_id"] for s in spans}
    for s in sorted(spans, key=lambda x: x["start"]):
        parent = s["parent_id"] if s["parent_id"] in ids else None
        by_parent.setdefault(parent, []).append(s)
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for s in by_parent.get(parent, []):
            mark = "✗ " if s["status"] == "error" else ""
            attrs = ""
            if show_attrs:
                attrs = " ".join(f"{k}={v}" for k, v in s["attrs"].items() if k not in _SKIP_ATTRS and v not in ("", None))
            lines.append(f"{'  ' * depth}{mark}[{s['service']}] {s['component']}: {s['name']} "
                         f"({s['duration_ms']:.1f} ms) {attrs}".rstrip())
            walk(s["span_id"], depth + 1)

    walk(None, 0)
    return "\n".join(lines)
