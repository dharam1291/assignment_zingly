"""Read the local trace collector (.run/traces.jsonl).

    python scripts/trace.py --last 5                 # the last 5 traces, as span trees
    python scripts/trace.py <trace_id>               # one trace
    python scripts/trace.py --conversation conv-...  # every turn of one conversation
    python scripts/trace.py --components             # which component emitted which span names
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from zingly_core import tracing

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("trace_id", nargs="?")
    p.add_argument("--file", default=os.environ.get("ZINGLY_TRACE_FILE", str(ROOT / ".run" / "traces.jsonl")))
    p.add_argument("--last", type=int)
    p.add_argument("--conversation")
    p.add_argument("--components", action="store_true")
    args = p.parse_args()

    spans = tracing.read_spans(args.file)
    if not spans:
        print(f"no spans in {args.file}")
        return 1
    if args.components:
        seen: dict[tuple[str, str], set[str]] = {}
        for s in spans:
            seen.setdefault((s["service"], s["component"]), set()).add(s["name"])
        for (service, comp), names in sorted(seen.items()):
            print(f"{service:16} {comp:14} {', '.join(sorted(names))}")
        return 0
    if args.trace_id:
        ids = [args.trace_id]
    elif args.conversation:
        ids = list(dict.fromkeys(s["trace_id"] for s in spans if s["attrs"].get("conversation_id") == args.conversation))
    else:
        roots = [s for s in spans if s["parent_id"] is None]
        ids = list(dict.fromkeys(s["trace_id"] for s in sorted(roots, key=lambda x: x["start"])))[-(args.last or 3):]
    for tid in ids:
        print(f"── trace {tid}")
        print(tracing.render_tree([s for s in spans if s["trace_id"] == tid]))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
