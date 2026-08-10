#!/usr/bin/env python
"""
scripts/drop_truncated_feeds.py
Remove feed entries whose summary was cut mid-sentence.

Agent summaries were truncated at 300 characters until AGENT_SUMMARY_LIMIT
raised it and truncate() learned to stop on a sentence. Rows collected before
that stay cut, and a half-sentence in the feed reads as a collection failure.
Rather than display them, drop them.

Deleting from seen_hashes also drops the dedup memory for that content, which
is the point: the same event becomes eligible for collection again and comes
back complete.

    python scripts/drop_truncated_feeds.py            # report only
    python scripts/drop_truncated_feeds.py --apply    # delete
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Summaries carry emoji ("📊 Social Intelligence Summary"), and this console is
# cp1252 by default -- printing one raises UnicodeEncodeError and takes the
# script down mid-run. Same trap that once killed four agents a cycle.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("drop-truncated")

# U+2026 only. A summary that legitimately ends in "..." typed as three periods
# is not what this is about, and matching it would delete real content.
ELLIPSIS = "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete")
    args = ap.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT.parent / ".env")
    except Exception:  # noqa: BLE001
        pass

    from src.storage.storage_manager import StorageManager

    store = StorageManager()
    cache = store.sqlite_cache

    entries = cache.get_all_entries(limit=100000, offset=0)
    cut = [e for e in entries
           if (e.get("summary_preview") or "").rstrip().endswith(ELLIPSIS)]

    print(f"  entries scanned : {len(entries)}")
    print(f"  ending mid-cut  : {len(cut)}")
    for e in cut[:5]:
        print("    -", (e.get("summary_preview") or "")[:80])
    if not cut:
        return 0
    if not args.apply:
        print("\n  dry run; pass --apply to delete")
        return 0

    ids = [e.get("event_id") for e in cut if e.get("event_id")]
    hashes = [e.get("content_hash") for e in cut if e.get("content_hash")]

    # ChromaDB first: if this half fails, the SQLite rows are still present and
    # the script can be re-run. The reverse order would strand vectors with no
    # way left to find them.
    removed_vectors = 0
    try:
        if ids:
            store.chromadb.collection.delete(ids=ids)
            removed_vectors = len(ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("chromadb delete failed: %s", exc)

    removed_rows = 0
    try:
        from src.storage.seen_hashes_model import SeenHash

        with cache._session() as session:
            for h in hashes:
                row = session.get(SeenHash, h)
                if row is not None:
                    session.delete(row)
                    removed_rows += 1
    except Exception as exc:  # noqa: BLE001
        logger.error("seen_hashes delete failed: %s", exc)

    print(f"\n  vectors removed : {removed_vectors}")
    print(f"  rows removed    : {removed_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
