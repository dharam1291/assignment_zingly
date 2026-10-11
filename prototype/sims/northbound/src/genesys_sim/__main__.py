"""Place a simulated call through the Genesys simulator (northbound, :8090).

    python -m genesys_sim                                   # interactive, Atlantica line
    python -m genesys_sim --dialed +4780001234 --caller +4791000001
    python -m genesys_sim --say yes --say "my flight was cancelled" --say ABC123 --say Smith --trace
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap

import httpx


def box(title: str, lines: list[str]) -> str:
    width = max([len(title) + 4, *(len(line) for line in lines)]) + 2
    out = [f"┌─ {title} " + "─" * (width - len(title) - 3) + "┐"]
    out += [f"│ {line.ljust(width - 2)} │" for line in lines]
    out.append("└" + "─" * width + "┘")
    return "\n".join(out)


def screen_pop(call: dict) -> str:
    h = call.get("screen_pop")
    if not h:
        return box("Genesys: human queue", [f"Queue: {call.get('queue')}", f"Reason: {call.get('reason')}",
                                             f"Disposition: {call.get('disposition')} (wait {call.get('estimated_wait_s')} s)"])
    r, c = h["routing"], h["caller"]
    lines = [f"Queue: {r['queue']}   priority {r['priority']}   {call['disposition']} (wait {call['estimated_wait_s']} s)",
             f"Category: {r['category']} / {r['subcategory']}",
             f"Caller: {c['number_masked']}   identity: {c['identity_level']}"
             + (f" ({c['verified_by']})" if c["verified_by"] else "")]
    if h.get("booking"):
        lines.append(f"Booking: {h['booking']['ref_masked']} on {h['booking']['flight']} ({h['booking']['cabin']})")
    if h.get("disruption"):
        d = h["disruption"]
        lines.append(f"Disruption: {d.get('flight')} {d.get('status')} ({d.get('reason') or 'reason n/a'})")
    lines.append("Summary:")
    lines += ["  " + line for line in textwrap.wrap(h["summary"], 72)]
    if h["attempted_actions"]:
        lines.append("Attempted actions:")
        for a in h["attempted_actions"]:
            extra = " ".join(f"{k}={v}" for k, v in a["args"].items())
            lines.append(f"  - {a['action']} {extra} -> {a['result']}" + (f" ({a['detail']})" if a["detail"] else ""))
    for note in h.get("data_notes", []):
        lines.append(f"Note: {note}")
    lines.append(f"Context (Data Action): {h['context_ref']}")
    return box("Genesys agent desktop: screen-pop", lines)


def print_trace(http: httpx.Client, trace_id: str | None) -> None:
    if trace_id:
        tree = http.get(f"/api/traces/{trace_id}").json()["tree"]
        print(textwrap.indent(tree or "(no spans: is ZINGLY_TRACE_FILE set for the services?)", "         │ "))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--genesys", default="http://127.0.0.1:8090")
    p.add_argument("--dialed", default="+448000001234", help="number the caller dials (selects the tenant)")
    p.add_argument("--caller", default="+447700900001", help="caller ID (ANI)")
    p.add_argument("--say", action="append", help="scripted caller lines (non-interactive)")
    p.add_argument("--trace", action="store_true", help="print the distributed trace of every turn")
    p.add_argument("--json", action="store_true", help="print the raw AGENT_HANDOVER payload")
    args = p.parse_args(argv)

    with httpx.Client(base_url=args.genesys, timeout=60) as http:
        call = http.post("/api/calls", json={"dialed": args.dialed, "caller": args.caller}).json()
        print(f"☎  {args.caller} dials {args.dialed} ({call.get('flow')}), Genesys call {call.get('call_id')}")
        if call.get("status") != "IN_BOT":
            print(f"Genesys routed the call to {call.get('routed_to')}: {call.get('reason')}\n")
            print(screen_pop(call))
            return 0
        print(f"Genesys: routed to Zingly ({call['tenant_id']}), room {call['room_id']}\n")
        print(f"BOT    > {call['transcript'][0]['text']}")
        if args.trace:
            print_trace(http, call["trace_id"])

        script = list(args.say or [])
        while True:
            if script:
                line = script.pop(0)
                print(f"CALLER > {line}")
            elif args.say:
                print("\n(script finished)")
                break
            else:
                try:
                    line = input("CALLER > ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
            if not line.strip():
                continue
            res = http.post(f"/api/calls/{call['call_id']}/say", json={"text": line}).json()
            t = res["turn"]
            tag = f"[{t['turn_path']}" + (f" → {t['agent']}" if t["agent"] else "") + \
                  f" | {t['identity_level']} | {t['latency_ms']} ms]"
            print(f"BOT    > {t['reply']['text']}\n         {tag}")
            if args.trace:
                print_trace(http, t["genesys_trace_id"])
            status = res["call"]["status"]
            if status == "COMPLETED":
                print("\nGenesys: the bot completed the call; the caller hangs up.")
                break
            if status == "AGENT_HANDOVER":
                full = http.get(f"/api/calls/{call['call_id']}").json()
                print("\nGenesys: conversation_status=AGENT_HANDOVER, routing to a human agent.\n")
                print(screen_pop(full))
                if args.json:
                    print(json.dumps(full["screen_pop"], indent=2))
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
