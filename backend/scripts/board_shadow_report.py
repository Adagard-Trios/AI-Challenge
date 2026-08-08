#!/usr/bin/env python
"""
scripts/board_shadow_report.py
Was the scheduler right?

WHAT THIS IS FOR
----------------
The blackboard controller runs in shadow: every cycle it computes the agenda it
WOULD follow and writes it to ks_activations with executed=False, while the
existing fan-out collects everything exactly as before.

This reads that ledger and answers the only question that should decide whether
to flip BLACKBOARD_CONTROL=active:

    For each knowledge source the controller wanted to SKIP, was anything
    actually being produced while it was skipped?

If a source it consistently skipped kept yielding high-salience entries, the
TRIGGER IS WRONG -- and finding that here is much better than finding it in a
feed that quietly went thin. That failure ("the feed looks dead") has happened
in this project more than once and taken a while to notice each time.

WHAT IT CANNOT TELL YOU
-----------------------
Shadow mode records intent, not outcomes, so it cannot attribute a board entry
to the source that would have produced it -- the fan-out produced everything.
What it CAN show is whether a source was being skipped during periods when its
domain was productive, which is the signal that matters. Stated plainly here
because a report that overclaims is worse than none.

    python scripts/board_shadow_report.py            # last 24 hours
    python scripts/board_shadow_report.py --hours 6
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=24,
                        help="how far back to look (default 24)")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:  # noqa: BLE001
        pass

    if not (os.getenv("DATABASE_URL") or "").strip():
        print("DATABASE_URL is unset, so the ledger is on local SQLite and\n"
              "will only contain this machine's cycles. That is fine for a\n"
              "laptop; on a deployment set DATABASE_URL first.\n")

    try:
        from auth.db import session_scope
        from src.blackboard.models import BoardEntry, KSActivation
        from src.blackboard.knowledge_sources import REGISTRY
    except Exception as exc:  # noqa: BLE001
        print(f"could not load the board: {exc}")
        return 1

    since = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    try:
        with session_scope() as session:
            rows = (
                session.query(KSActivation)
                .filter(KSActivation.decided_at >= since)
                .all()
            )
            entries = (
                session.query(BoardEntry)
                .filter(BoardEntry.level == "event",
                        BoardEntry.created_at >= since)
                .all()
            )
            rows = [
                {
                    "ks_name": r.ks_name,
                    "executed": bool(r.executed),
                    "skipped_reason": r.skipped_reason,
                    "priority": float(r.priority or 0),
                    "trigger_reason": r.trigger_reason,
                    "est_tokens": int(r.est_tokens or 0),
                    "decided_at": _aware(r.decided_at),
                }
                for r in rows
            ]
            productive = defaultdict(int)
            salient = defaultdict(int)
            for entry in entries:
                domain = entry.domain or "unknown"
                productive[domain] += 1
                if float(entry.salience or 0) >= 0.5:
                    salient[domain] += 1
    except Exception as exc:  # noqa: BLE001
        print(f"could not read the ledger: {exc}")
        return 1

    if not rows:
        print(f"No activations in the last {args.hours}h.\n"
              "The controller records one row per source per cycle, so an\n"
              "empty ledger means it has not run -- check BLACKBOARD_ENABLED\n"
              "and that the agent loop is running.")
        return 0

    ticks = len({r["decided_at"].replace(microsecond=0) for r in rows})
    print(f"\nShadow report -- last {args.hours}h, {len(rows)} activations "
          f"across ~{ticks} ticks\n")

    by_source = defaultdict(list)
    for row in rows:
        by_source[row["ks_name"]].append(row)

    print(f"{'knowledge source':<28} {'planned':>7} {'skipped':>8} "
          f"{'skip%':>6} {'avg prio':>9}  domain yield")
    print("-" * 88)

    suspicious = []
    for name in sorted(by_source):
        source_rows = by_source[name]
        planned = len(source_rows)
        # "shadow" is not a judgement -- it means the controller was not
        # executing at all. Only real refusals count as a decision to skip.
        refused = sum(1 for r in source_rows
                      if r["skipped_reason"] not in (None, "shadow"))
        pct = (refused / planned * 100) if planned else 0
        avg = sum(r["priority"] for r in source_rows) / max(1, planned)

        source = REGISTRY.get(name)
        domain = source.domain if source else "?"
        yield_note = f"{salient.get(domain, 0)} salient / {productive.get(domain, 0)}"

        print(f"{name:<28} {planned:>7} {refused:>8} {pct:>5.0f}% "
              f"{avg:>9.3f}  {yield_note}")

        # The finding worth acting on: refused most of the time, in a domain
        # that was nonetheless producing salient entries.
        if pct >= 50 and salient.get(domain, 0) >= 3:
            suspicious.append((name, pct, domain, salient[domain]))

    print()
    if suspicious:
        print("LOOK AT THESE. Refused often, in a domain that kept producing:\n")
        for name, pct, domain, count in suspicious:
            print(f"  {name}: refused {pct:.0f}% of the time while "
                  f"{domain} produced {count} salient entries")
        print("\nThat is the shape of a wrong trigger. Widen it, or lower its\n"
              "max_interval, BEFORE setting BLACKBOARD_CONTROL=active.")
    else:
        print("No source was refused often while its domain stayed productive.")

    never_run = [n for n in REGISTRY if n not in by_source]
    if never_run:
        print(f"\nNever planned at all: {', '.join(sorted(never_run))}")
        print("A source that never reaches the agenda is either correctly "
              "quiet or has\na trigger that can never fire. The max_interval "
              "floor should prevent the\nsecond, so check it.")

    not_executable = [n for n, s in REGISTRY.items() if not s.executable]
    if not_executable:
        print(f"\nPlanned but NOT executable: {', '.join(sorted(not_executable))}")
        print("These have no run(). They would be recorded and skipped rather "
              "than\nsilently reported as done -- but they also mean going "
              "active would\ncollect less than the fan-out does today.")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
