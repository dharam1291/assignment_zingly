"""Turn flow runs and their recorded spans into Markdown documentation (used by run_flow --record).

Everything in the generated pages comes from the run: the transcript, the screen-pop, the
components that took part, the sequence diagram and the span trees are built from the
spans the four services wrote to the trace collector during that run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from zingly_core import tracing

# component -> (mermaid id, label), in diagram order
COMPONENTS = {
    "genesys": ("G", "Genesys (northbound)"),
    "gateway": ("GW", "Voice agent gateway"),
    "ai-router": ("R", "AI router"),
    "agents": ("AG", "Agents"),
    "auth": ("AU", "Auth"),
    "handover": ("HO", "Handover"),
    "mcp-client": ("MC", "MCP client"),
    "mcp-server": ("MS", "MCP server"),
    "policy": ("PO", "Policy engine"),
    "saved-copy": ("SC", "Saved copy"),
    "pss-adapter": ("PA", "PSS adapter"),
    "airline-pss": ("PSS", "Airline PSS (southbound)"),
}
SKIP = {"channel.inbound"}
BACKGROUND_ROOTS = {"gateway.disruption_event", "mcp.drain_deferred"}
KEY_ATTRS = ("tool", "lane", "agent", "operation", "resource", "flight", "path", "kind")
RESULT_ATTRS = ("status", "source", "admitted", "outcome", "allowed", "level", "http_status", "accept", "routed_to")


def _clean(text: str, limit: int = 70) -> str:
    text = str(text).replace(";", ",").replace("#", "").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _label(span: dict) -> str:
    extra = " ".join(f"{k}={span['attrs'][k]}" for k in KEY_ATTRS if k in span["attrs"])
    return _clean(f"{span['name']} {extra}".strip())


def _result(span: dict) -> str:
    bits = [f"{k}={span['attrs'][k]}" for k in RESULT_ATTRS if k in span["attrs"]]
    if span["status"] == "error":
        bits.append("ERROR")
    return _clean(", ".join(bits) or "done", 60)


def _children(spans: list[dict]) -> dict[str | None, list[dict]]:
    ids = {s["span_id"] for s in spans}
    out: dict[str | None, list[dict]] = {}
    for s in sorted(spans, key=lambda x: x["start"]):
        out.setdefault(s["parent_id"] if s["parent_id"] in ids else None, []).append(s)
    return out


def sequence(turns: list[tuple[str, str, list[dict]]]) -> str:
    """Mermaid sequence diagram: one arrow per hop between components, with the result back."""
    used: set[str] = set()
    body: list[str] = []
    for caller_text, bot_text, spans in turns:
        if not spans:
            continue
        kids = _children(spans)
        body.append(f"    Note over C,G: {_clean(caller_text, 60) if caller_text else 'call set-up'}")
        if caller_text:
            body.append(f"    C->>G: {_clean(caller_text, 50)}")

        def walk(parent: dict) -> None:
            for child in kids.get(parent["span_id"], []):
                if child["name"] in SKIP:
                    continue
                pc, cc = parent["component"], child["component"]
                if cc != pc and pc in COMPONENTS and cc in COMPONENTS:
                    a, b = COMPONENTS[pc][0], COMPONENTS[cc][0]
                    used.update((pc, cc))
                    body.append(f"    {a}->>{b}: {_label(child)}")
                    walk(child)
                    body.append(f"    {b}-->>{a}: {_result(child)}")
                else:
                    walk(child)

        for root in kids.get(None, []):
            if root["component"] in COMPONENTS:
                used.add(root["component"])
            walk(root)
        if bot_text:
            body.append(f"    G-->>C: {_clean(bot_text, 60)}")
    head = ["```mermaid", "sequenceDiagram", "    autonumber", "    actor C as Caller"]
    for comp, (alias, label) in COMPONENTS.items():
        if comp in used or comp == "genesys":
            head.append(f"    participant {alias} as {label}")
    return "\n".join(head + body + ["```"])


def components_table(spans: list[dict]) -> str:
    rows: dict[tuple[str, str], set[str]] = {}
    for s in spans:
        rows.setdefault((s["service"], s["component"]), set()).add(s["name"])
    out = ["| Process | Component | Operations seen in this run |", "|---|---|---|"]
    for (service, comp), names in sorted(rows.items()):
        out.append(f"| `{service}` | {comp} | {', '.join(f'`{n}`' for n in sorted(names))} |")
    return "\n".join(out)


def _tree(spans: list[dict]) -> str:
    return "```text\n" + (tracing.render_tree(spans) or "(no spans)") + "\n```"


def write_flow(run, trace_file: str, out_dir: Path) -> Path:
    spec = run.spec
    all_spans: list[dict] = []
    lines = [f"# Flow {run.name.split('_', 1)[0]}: {spec['title']}", "",
             spec["summary"].strip(), "",
             f"**Demonstrates:** {', '.join(str(d) for d in spec.get('demonstrates', []))}", "",
             f"**Result:** {'PASS' if run.passed else 'FAIL'} · recorded {time.strftime('%Y-%m-%d %H:%M', time.localtime(run.started))}"
             f" · re-run with `python scripts/run_flow.py {run.name} --trace`", ""]
    if spec.get("_setup_log"):
        lines += ["## Setup", ""] + [f"- {m}" for m in spec["_setup_log"]] + [""]

    for idx, call in enumerate(run.calls, 1):
        title = f"## Call {idx}: {call.caller} dials {call.dialed}" if len(run.calls) > 1 else "## Conversation"
        lines += [title, "", f"Genesys routed the call to **{call.routed_to}**" + (f" ({call.reason})." if call.reason else "."), ""]
        turns_for_seq = []
        welcome_spans = tracing.read_spans(trace_file, call.welcome_trace) if call.welcome_trace else []
        all_spans += welcome_spans
        turns_for_seq.append(("", call.welcome, welcome_spans))
        if call.turns or call.welcome:
            lines += ["| # | Caller | Bot | Path → agent | Identity | ms |", "|---|---|---|---|---|---|"]
            if call.welcome:
                lines.append(f"| 0 | *(dials)* | {call.welcome} | welcome (pre-rendered) | unknown | |")
            for n, t in enumerate(call.turns, 1):
                path = (t.path or "") + (f" → {t.agent}" if t.agent else "")
                lines.append(f"| {n} | {t.caller} | {t.bot} | {path} | {t.identity} | {t.latency_ms} |")
            lines.append("")
        pop = call.final.get("screen_pop")
        if pop:
            lines += ["### Handover: Genesys screen-pop", "",
                      f"Queue **{pop['routing']['queue']}**, {call.final.get('disposition')} "
                      f"(estimated wait {call.final.get('estimated_wait_s')} s).", "",
                      "```json", json.dumps({k: v for k, v in pop.items() if k != "context_expires_at"}, indent=2), "```", ""]
        elif call.routed_to == "human_queue":
            lines += [f"Queued for a person on **{call.final.get('queue')}**, {call.final.get('disposition')}.", ""]
        turn_traces = []
        for n, t in enumerate(call.turns, 1):
            spans = tracing.read_spans(trace_file, t.trace_id)
            all_spans += spans
            turns_for_seq.append((t.caller, t.bot, spans))
            turn_traces.append((n, t, spans))
        lines += ["### Sequence (built from the recorded spans)", "", sequence(turns_for_seq), ""]
        lines += ["### Traces", "", "<details><summary>Call set-up</summary>", "", _tree(welcome_spans), "", "</details>", ""]
        for n, t, spans in turn_traces:
            lines += [f"<details><summary>Turn {n}: “{t.caller}”</summary>", "", _tree(spans), "", "</details>", ""]

    if run.mcp_steps:
        lines += ["## MCP client session", "", "| Request | Identity | Result |", "|---|---|---|"]
        mcp_turns = []
        for step in run.mcp_steps:
            res = step["result"]
            shown = res if isinstance(res, list) else f"{res['status']}" + (f": {res['detail']}" if res.get("detail") else "")
            lines.append(f"| `{step['op']}` {json.dumps(step.get('args', ''))} | {step.get('identity', '')} | {_clean(shown, 120)} |")
            if step.get("trace_id"):
                spans = tracing.read_spans(trace_file, step["trace_id"])
                all_spans += spans
                mcp_turns.append((step["op"], spans))
        lines += ["", "### Traces", ""]
        for op, spans in mcp_turns:
            lines += [f"<details><summary>{op}</summary>", "", _tree(spans), "", "</details>", ""]

    background = [s for s in tracing.read_spans(trace_file)
                  if s["parent_id"] is None and s["name"] in BACKGROUND_ROOTS and run.started <= s["start"] <= run.ended]
    if background:
        lines += ["## Background work during this flow", ""]
        for root in background:
            spans = tracing.read_spans(trace_file, root["trace_id"])
            all_spans += spans
            lines += [f"<details><summary>{root['name']} ({root['duration_ms']:.0f} ms)</summary>", "", _tree(spans), "",
                      "</details>", ""]

    lines += ["## Components involved", "", components_table(all_spans), "", "## Checks", ""]
    lines += [f"- {'✅' if ok else '❌'} {what}" for ok, what in run.results] + [""]
    out = out_dir / f"{run.name}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out, {s["component"] for s in all_spans}


def write_docs(runs, trace_file: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = ["# Recorded flows", "",
            "Each page is generated by `python scripts/run_flow.py --all --record` from a real run against the four",
            "running services: the transcript, the screen-pop, the components involved, a sequence diagram and the",
            "span tree of every turn all come from the spans the services wrote during that run.", "",
            "| Flow | What it shows | Result |", "|---|---|---|"]
    used: dict[str, set[str]] = {}
    for run in runs:
        path, comps = write_flow(run, trace_file, out_dir)
        used[run.name] = comps
        rows.append(f"| [{run.name}]({path.name}) | {run.spec['title']} | {'PASS' if run.passed else 'FAIL'} |")
    order = [c for c in [*COMPONENTS, "channel"] if any(c in u for u in used.values())]
    rows += ["", "## Components each flow used", "",
             "Taken from the spans of each run (● = at least one span from that component).", "",
             "| Flow | " + " | ".join(order) + " |", "|---|" + "---|" * len(order)]
    for name, comps in used.items():
        rows.append(f"| {name.split('_', 1)[0]} | " + " | ".join("●" if c in comps else "" for c in order) + " |")
    (out_dir / "README.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
