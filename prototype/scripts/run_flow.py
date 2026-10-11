"""Run demonstration flows against the running servers (start them with ./start_up.sh).

    python scripts/run_flow.py --list
    python scripts/run_flow.py happy_rebooking            # one flow (name or number prefix)
    python scripts/run_flow.py 01 07 --trace              # several, with the distributed trace per turn
    python scripts/run_flow.py --all                      # every flow, PASS/FAIL summary
    python scripts/run_flow.py --all --record             # also write docs/flows/*.md from the real traces

A flow is a YAML file in flows/: setup actions (fault injection, lane saturation, capacity),
calls placed through the Genesys simulator with caller lines and expectations, optional
direct MCP client steps, and end-state checks against the reservation system.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from zingly_core import IdentityLevel, TenantConfigStore, identity_token, tracing

ROOT = Path(__file__).resolve().parents[1]
FLOWS = ROOT / "flows"
DOCS = ROOT / "docs" / "flows"
GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = DIM = BOLD = OFF = ""


@dataclass
class Turn:
    caller: str
    bot: str
    path: str | None
    agent: str | None
    identity: str
    status: str
    latency_ms: float
    trace_id: str


@dataclass
class CallLog:
    dialed: str
    caller: str
    routed_to: str
    reason: str = ""
    welcome: str = ""
    welcome_trace: str = ""
    turns: list[Turn] = field(default_factory=list)
    final: dict = field(default_factory=dict)


@dataclass
class FlowRun:
    name: str
    spec: dict
    calls: list[CallLog] = field(default_factory=list)
    mcp_steps: list[dict] = field(default_factory=list)
    results: list[tuple[bool, str]] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    ended: float = 0.0

    def check(self, ok: bool, what: str) -> None:
        self.results.append((bool(ok), what))

    @property
    def passed(self) -> bool:
        return all(ok for ok, _ in self.results)


class Env:
    def __init__(self) -> None:
        store = TenantConfigStore.from_file(ROOT / "config" / "tenants.yml")
        self.store = store
        self.genesys = store.platform("genesys_url")
        self.va = store.platform("voice_agent_url")
        self.mcp = store.platform("mcp_server_url")
        self.pss = store.platform("pss_url")
        self.trace_file = str(ROOT / store.platform("trace_file", ".run/traces.jsonl"))
        self.http = httpx.AsyncClient(timeout=90)
        with open(ROOT / "sims" / "northbound" / "genesys.yml", encoding="utf-8") as fh:
            self.inbound_numbers = list(yaml.safe_load(fh)["inbound_flows"])

    async def preflight(self) -> None:
        for name, url in [("genesys", f"{self.genesys}/health"), ("voice agent", f"{self.va}/health"),
                          ("MCP server", f"{self.mcp}/health"), ("PSS", f"{self.pss}/stats")]:
            try:
                (await self.http.get(url, timeout=3)).raise_for_status()
            except httpx.HTTPError:
                sys.exit(f"{name} is not reachable at {url}. Start everything with ./start_up.sh")

    # ---- actions -------------------------------------------------------------------
    async def action(self, act: dict) -> str:
        (kind, arg), = act.items()
        h = self.http
        if kind == "reset":
            await h.post(f"{self.pss}/admin/reset")
            for t in self.store.tenant_ids:
                await h.post(f"{self.mcp}/admin/{t}/reset")
            await h.post(f"{self.va}/v1/admin/reset")
            return "reset PSS data, MCP lanes/saved copy/breaker, voice-agent sessions and lockouts"
        if kind == "prewarm":
            r = (await h.post(f"{self.va}/v1/events/disruption", json={"tenant_id": arg["tenant"], "flight": arg["flight"]})).json()
            return f"disruption event for {arg['flight']}: saved copy pre-warmed ({r})"
        if kind == "pss_mode":
            await h.post(f"{self.pss}/admin/mode", json=arg)
            return f"PSS fault injection: {arg}"
        if kind == "pause_lanes":
            await h.post(f"{self.mcp}/admin/{arg['tenant']}/lanes/pause", json=arg)
            return f"lanes {arg['lanes']} saturated for {arg['seconds']} s"
        if kind == "protection":
            await h.post(f"{self.mcp}/admin/{arg['tenant']}/protection", json=arg)
            return f"protection {'on' if arg['enabled'] else 'off'} for {arg['tenant']}"
        if kind == "max_sessions":
            await h.post(f"{self.va}/v1/admin/tenants/{arg['tenant']}/max-sessions", json={"max_sessions": arg["max"]})
            return f"{arg['tenant']} max concurrent sessions = {arg['max']}"
        if kind == "bot_percent":
            await h.post(f"{self.genesys}/admin/flows/bot-percent", json={"dialed": arg["dialed"], "bot_percent": arg["percent"]})
            return f"Genesys inbound flow {arg['dialed']}: {arg['percent']}% to the bot"
        if kind == "wait":
            await asyncio.sleep(float(arg))
            return f"wait {arg} s"
        raise ValueError(f"unknown action {kind}")

    async def teardown(self) -> None:
        h = self.http
        for airline in ("atlantica", "nordica"):
            await h.post(f"{self.pss}/admin/mode", json={"airline": airline, "error_rate": 0, "extra_latency_ms": 0})
        for t in self.store.tenant_ids:
            await h.post(f"{self.mcp}/admin/{t}/protection", json={"enabled": True})
            await h.post(f"{self.va}/v1/admin/tenants/{t}/max-sessions", json={"max_sessions": 500})
        for number in self.inbound_numbers:
            await h.post(f"{self.genesys}/admin/flows/bot-percent", json={"dialed": number, "bot_percent": 100})


# ---- expectations --------------------------------------------------------------------
def _contains(text: str, needles: Any) -> bool:
    needles = [needles] if isinstance(needles, str) else needles
    return all(n.lower() in text.lower() for n in needles)


def evaluate(run: FlowRun, label: str, expect: dict, turn: Turn, call: dict) -> None:
    for key, want in expect.items():
        if key == "contains":
            run.check(_contains(turn.bot, want), f"{label}: reply contains {want!r}")
        elif key == "contains_any":
            run.check(any(w.lower() in turn.bot.lower() for w in want), f"{label}: reply contains one of {want!r}")
        elif key in ("path", "agent", "identity"):
            got = getattr(turn, key)
            run.check(got == want, f"{label}: {key} = {want} (got {got})")
        elif key == "status":
            got = {"IN_BOT": "IN_PROGRESS"}.get(call["status"], call["status"])
            run.check(got == want, f"{label}: call status {want} (got {got})")
        elif key == "handover":
            pop = call.get("screen_pop") or {}
            got = {"subcategory": pop.get("routing", {}).get("subcategory"),
                   "queue": pop.get("routing", {}).get("queue"),
                   "identity": pop.get("caller", {}).get("identity_level"),
                   "disposition": call.get("disposition")}
            for k, v in want.items():
                run.check(got.get(k) == v, f"{label}: handover {k} = {v} (got {got.get(k)})")
        else:
            run.check(False, f"{label}: unknown expectation {key}")


def subset(want: Any, got: Any) -> bool:
    if isinstance(want, dict):
        return isinstance(got, dict) and all(subset(v, got.get(k)) for k, v in want.items())
    return want == got


# ---- runners -------------------------------------------------------------------------
async def run_call(env: Env, run: FlowRun, idx: int, spec: dict, verbose: bool, show_trace: bool) -> None:
    g = env.http
    call = (await g.post(f"{env.genesys}/api/calls", json={"dialed": spec["dialed"], "caller": spec["caller"]})).json()
    log = CallLog(spec["dialed"], spec["caller"], call["routed_to"], call.get("reason", ""),
                  call["transcript"][0]["text"] if call.get("transcript") else "", call.get("trace_id", ""))
    run.calls.append(log)
    label = f"call {idx}"
    print(f"\n{BOLD}☎  {label}: {spec['caller']} → {spec['dialed']}{OFF}  routed to {log.routed_to}"
          + (f" ({log.reason})" if log.reason else ""))
    want_route = spec.get("expect_routed", "zingly")
    run.check(log.routed_to == want_route, f"{label}: routed to {want_route} (got {log.routed_to})")
    if "expect_reason_contains" in spec:
        run.check(spec["expect_reason_contains"] in log.reason, f"{label}: reason mentions {spec['expect_reason_contains']}")
    if "expect_welcome_contains" in spec:
        run.check(_contains(log.welcome, spec["expect_welcome_contains"]), f"{label}: welcome {spec['expect_welcome_contains']!r}")
    if log.welcome:
        print(f"   BOT    > {log.welcome}")
    if show_trace and log.welcome_trace:
        print_trace(env, log.welcome_trace)
    if call["status"] != "IN_BOT":
        log.final = call
        return

    for n, step in enumerate(spec.get("steps", []), 1):
        if "do" in step:
            print(f"   {DIM}· {await env.action(step['do'])}{OFF}")
            continue
        if "wait" in step:
            print(f"   {DIM}· {await env.action({'wait': step['wait']})}{OFF}")
            continue
        state = (await g.get(f"{env.genesys}/api/calls/{call['call_id']}")).json()
        if state["status"] != "IN_BOT":
            run.check(False, f"{label} turn {n}: call already {state['status']}, cannot say {step['say']!r}")
            break
        res = (await g.post(f"{env.genesys}/api/calls/{call['call_id']}/say", json={"text": step["say"]})).json()
        t, c = res["turn"], res["call"]
        turn = Turn(step["say"], t["reply"]["text"], t["turn_path"], t["agent"], t["identity_level"],
                    c["status"], t["latency_ms"], t["genesys_trace_id"])
        log.turns.append(turn)
        tag = f"{turn.path}" + (f" → {turn.agent}" if turn.agent else "") + f" | {turn.identity} | {turn.latency_ms} ms"
        print(f"   CALLER > {turn.caller}\n   BOT    > {turn.bot}\n            {DIM}[{tag}]{OFF}")
        if show_trace:
            print_trace(env, turn.trace_id)
        full = (await g.get(f"{env.genesys}/api/calls/{call['call_id']}")).json()
        evaluate(run, f"{label} turn {n}", step.get("expect", {}), turn, full)
    log.final = (await g.get(f"{env.genesys}/api/calls/{call['call_id']}")).json()
    if log.final.get("screen_pop") and verbose:
        pop = log.final["screen_pop"]
        print(f"   {DIM}screen-pop → queue {pop['routing']['queue']} · {pop['routing']['subcategory']} · "
              f"{log.final.get('disposition')} · {pop['summary']}{OFF}")


async def run_mcp(env: Env, run: FlowRun, spec: dict) -> None:
    tenant = spec["tenant"]
    url = f"{env.mcp}/{tenant}/mcp"
    key = identity_token.signing_key(tenant)
    print(f"\n{BOLD}⚙  MCP client → {url}{OFF}")
    async with streamable_http_client(url, http_client=env.http, terminate_on_close=False) as (r, w, _):
        async with ClientSession(r, w) as session:
            info = await session.initialize()
            print(f"   initialize → {info.serverInfo.name} (protocol {info.protocolVersion})")
            for n, step in enumerate(spec["steps"], 1):
                label = f"mcp step {n}"
                if "list_tools" in step:
                    names = [t.name for t in (await session.list_tools()).tools]
                    print(f"   tools/list → {names}")
                    run.mcp_steps.append({"op": "tools/list", "result": names})
                    for want in step["list_tools"].get("expect_contains", []):
                        run.check(want in names, f"{label}: tools/list includes {want}")
                    continue
                c = step["call"]
                meta, who = {}, "no identity token"
                if "identity" in c:
                    ident = c["identity"]
                    meta["identity_token"] = identity_token.issue(key, tenant, "flow-runner", IdentityLevel.parse(ident["level"]),
                                                                  ident.get("booking_ref"), 300)
                    who = f"token {ident['level']} for {ident.get('booking_ref')}"
                with tracing.span("flow.mcp_call", "mcp-client", tool=c["tool"], identity=who) as sp:
                    meta["traceparent"] = sp.traceparent
                    res = await session.call_tool(c["tool"], c.get("args", {}), meta=meta)
                out = res.structuredContent or json.loads(res.content[0].text)
                print(f"   tools/call {c['tool']} {c.get('args', {})} [{who}]\n            → {out['status']}"
                      + (f": {out['detail']}" if out.get("detail") else "")
                      + (f" {DIM}{json.dumps(out['data'])[:140]}{OFF}" if out.get("data") else ""))
                run.mcp_steps.append({"op": f"tools/call {c['tool']}", "args": c.get("args", {}), "identity": who,
                                      "result": out, "trace_id": sp.trace_id})
                run.check(subset(c.get("expect", {}), out), f"{label}: {c['tool']} → {c.get('expect')}")


async def run_checks(env: Env, run: FlowRun, baseline: dict) -> None:
    for chk in run.spec.get("checks", []):
        (kind, arg), = chk.items()
        if kind == "pss_booking":
            b = (await env.http.get(f"{env.pss}/admin/booking/{arg['airline']}/{arg['ref']}")).json()
            run.check(b.get("flight") == arg["flight"], f"check: PSS booking {arg['ref']} on {arg['flight']} (got {b.get('flight')})")
        elif kind == "deferred":
            got = (await env.http.get(f"{env.mcp}/admin/stats")).json()[arg["tenant"]]["deferred_commits"]
            run.check(got.get("confirmed", 0) >= arg["confirmed"], f"check: deferred commits confirmed ≥ {arg['confirmed']} (got {got})")
        elif kind == "pss_requests_since_setup":
            now = (await env.http.get(f"{env.pss}/stats")).json()[arg["airline"]].get("requests", 0)
            used = now - baseline.get(arg["airline"], 0)
            run.check(used <= arg["max"], f"check: PSS requests during the call ≤ {arg['max']} (got {used})")


def print_trace(env: Env, trace_id: str) -> None:
    time.sleep(0.05)  # let the services flush their span lines
    tree = tracing.render_tree(tracing.read_spans(env.trace_file, trace_id))
    for line in (tree or "(no spans recorded)").splitlines():
        print(f"            {DIM}│ {line}{OFF}")


async def run_flow(env: Env, path: Path, verbose: bool, show_trace: bool) -> FlowRun:
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    run = FlowRun(path.stem, spec)
    print(f"\n{BOLD}━━ {path.stem}: {spec['title']}{OFF}\n{DIM}{spec['summary'].strip()}{OFF}")
    try:
        spec["_setup_log"] = []
        for act in spec.get("setup", []):
            msg = await env.action(act)
            spec["_setup_log"].append(msg)
            print(f"   {DIM}· setup: {msg}{OFF}")
        stats = (await env.http.get(f"{env.pss}/stats")).json()
        baseline = {a: v.get("requests", 0) for a, v in stats.items()}
        for i, call in enumerate(spec.get("calls", []), 1):
            await run_call(env, run, i, call, verbose, show_trace)
        if "mcp" in spec:
            await run_mcp(env, run, spec["mcp"])
        await run_checks(env, run, baseline)
    finally:
        await env.teardown()
        run.ended = time.time()
    for ok, what in run.results:
        print(f"   {GREEN + '✓' if ok else RED + '✗'}{OFF} {what}")
    print(f"   {GREEN + 'PASS' if run.passed else RED + 'FAIL'}{OFF} {path.stem}")
    return run


def resolve(names: list[str]) -> list[Path]:
    files = sorted(FLOWS.glob("*.yml"))
    picked = []
    for n in names:
        match = [f for f in files if f.stem == n or f.stem.startswith(n) or f.stem.split("_", 1)[-1] == n]
        if not match:
            sys.exit(f"no flow named {n!r}; try --list")
        picked += match
    return picked


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("flows", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--list", action="store_true")
    p.add_argument("--trace", action="store_true", help="print the distributed trace of every turn")
    p.add_argument("--record", action="store_true", help="write docs/flows/<flow>.md from the run and its traces")
    args = p.parse_args()

    if args.list:
        for f in sorted(FLOWS.glob("*.yml")):
            spec = yaml.safe_load(f.read_text(encoding="utf-8"))
            print(f"{f.stem:34} {spec['title']}")
        return 0
    paths = sorted(FLOWS.glob("*.yml")) if args.all or not args.flows else resolve(args.flows)

    env = Env()
    tracing.configure("flow-runner", sink_path=env.trace_file)
    await env.preflight()
    runs = []
    for path in paths:
        runs.append(await run_flow(env, path, verbose=True, show_trace=args.trace))
    await env.http.aclose()

    if args.record:
        from record_flow import write_docs  # noqa: PLC0415 - only needed when recording
        write_docs(runs, env.trace_file, DOCS)
        print(f"\nwrote {len(runs)} flow documents to {DOCS.relative_to(ROOT)}/")
    failed = [r.name for r in runs if not r.passed]
    print(f"\n{BOLD}{len(runs) - len(failed)}/{len(runs)} flows passed{OFF}" + (f"  {RED}failed: {failed}{OFF}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
