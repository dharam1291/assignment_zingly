"""Simulated phone call through Genesys into Zingly.

    python -m genesys_sim --dialed +448000001234 --caller +447700900001
    python -m genesys_sim --dialed +448000001234 --caller +447700900001 \\
        --say yes --say "my flight was cancelled" --say ABC123 --say Smith --say first --say yes --say "no thanks"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import textwrap
import uuid

import httpx


def box(title: str, lines: list[str]) -> str:
    width = max([len(title) + 4, *(len(l) for l in lines)]) + 2
    out = [f"┌─ {title} " + "─" * (width - len(title) - 3) + "┐"]
    out += [f"│ {l.ljust(width - 2)} │" for l in lines]
    out.append("└" + "─" * width + "┘")
    return "\n".join(out)


def screen_pop(handover: dict, wait_s: int, callback_after_s: int) -> str:
    r, c = handover["routing"], handover["caller"]
    lines = [f"Queue: {r['queue']}   priority {r['priority']}",
             f"Category: {r['category']} / {r['subcategory']}",
             f"Caller: {c['number_masked']}   identity: {c['identity_level']}"
             + (f" ({c['verified_by']})" if c["verified_by"] else "")]
    if handover.get("booking"):
        b = handover["booking"]
        lines.append(f"Booking: {b['ref_masked']} on {b['flight']} ({b['cabin']})")
    if handover.get("disruption"):
        d = handover["disruption"]
        lines.append(f"Disruption: {d.get('flight')} {d.get('status')} ({d.get('reason') or 'reason n/a'})")
    lines.append("Summary:")
    lines += ["  " + l for l in textwrap.wrap(handover["summary"], 70)]
    if handover["attempted_actions"]:
        lines.append("Attempted actions:")
        for a in handover["attempted_actions"]:
            extra = " ".join(f"{k}={v}" for k, v in a["args"].items())
            lines.append(f"  - {a['action']} {extra} -> {a['result']}" + (f" ({a['detail']})" if a["detail"] else ""))
    for note in handover.get("data_notes", []):
        lines.append(f"Note: {note}")
    lines.append(f"Context (Data Action): {handover['context_ref']}")
    if r["callback_eligible"] and wait_s > callback_after_s:
        lines.append(f"Estimated wait {wait_s}s > {callback_after_s}s: callback offered, caller keeps their place.")
    else:
        lines.append(f"Estimated wait {wait_s}s: caller joins queue {r['queue']}.")
    return box("Genesys agent desktop: screen-pop", lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--zingly", default="http://127.0.0.1:8080")
    p.add_argument("--dialed", default="+448000001234", help="number the caller dialled (selects the tenant)")
    p.add_argument("--caller", default="+447700900001", help="caller ID (ANI)")
    p.add_argument("--bot-percent", type=int, default=100, help="Genesys A/B split: share of calls to Zingly")
    p.add_argument("--queue-wait", type=int, default=None, help="simulated queue wait in seconds")
    p.add_argument("--callback-after", type=int, default=120)
    p.add_argument("--say", action="append", help="scripted caller lines (non-interactive)")
    p.add_argument("--json", action="store_true", help="print raw handover JSON as well")
    args = p.parse_args(argv)

    call_id = f"genesys-{uuid.uuid4().hex[:8]}"
    print(f"☎  {args.caller} dials {args.dialed}  (Twilio -> Genesys, call {call_id})")
    if random.randint(1, 100) > args.bot_percent:
        print("Genesys: A/B split sent this call to the legacy IVR.")
        return 0

    with httpx.Client(base_url=args.zingly, timeout=30) as http:
        cap = http.get("/v1/capacity", params={"dialed_number": args.dialed}).json()
        if not cap.get("accept"):
            print(f"Genesys: Zingly capacity check said no ({cap.get('reasons')}): human queue with callback offer.")
            return 0
        created = http.post("/v1/conversations", json={"call_id": call_id, "dialed_number": args.dialed,
                                                        "caller_number": args.caller})
        if created.status_code != 200:
            print(f"Genesys: create conversation failed ({created.status_code}): error path to human queue.")
            return 0
        conv = created.json()
        print(f"Genesys: routed to Zingly ({conv['tenant_id']}), room {conv['room']['room_id']}\n")
        print(f"BOT    > {conv['reply']['text']}")

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
            r = http.post(f"/v1/conversations/{conv['conversation_id']}/utterances", json={"text": line}).json()
            tag = f"[{r['turn_path']}" + (f" → {r['agent']}" if r["agent"] else "") + f" | {r['identity_level']} | {r['latency_ms']} ms]"
            print(f"BOT    > {r['reply']['text']}\n         {tag}")
            if r["conversation_status"] == "COMPLETED":
                print("\nGenesys: bot completed the call. Caller hangs up.")
                break
            if r["conversation_status"] == "AGENT_HANDOVER":
                wait = args.queue_wait if args.queue_wait is not None else random.choice([20, 45, 300])
                print("\nGenesys: conversation_status=AGENT_HANDOVER, routing to a human agent.\n")
                print(screen_pop(r["handover"], wait, args.callback_after))
                if args.json:
                    print(json.dumps(r["handover"], indent=2))
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
