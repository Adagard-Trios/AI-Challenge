#!/usr/bin/env python
"""
scripts/snapshot_cse.py
Append one day's Colombo Stock Exchange closes to a local series.

WHY THIS EXISTS
---------------
The stock model was written against Yahoo Finance, which carries no CSE listing
in any symbol format -- COMB.N0000, COMB.CM, JKH.N0000 and JKH.CM all return
zero rows -- so every ticker failed to train and the panel ended up showing US
tickers labelled "CSE" in "LKR".

cse.lk publishes the real prices, but only the CURRENT ones: there is no
per-company history endpoint (chartData and companyPriceHistory both 400,
dailyMarketSummery is market-wide aggregates). So the history has to be built
rather than fetched. This appends today's close per symbol; run it once a day
and a trainable series accumulates.

Until it has enough rows, the dashboard shows prices and says plainly that it
has no forecast. That is the honest state, not a placeholder for one.

    python scripts/snapshot_cse.py            # append today
    python scripts/snapshot_cse.py --status   # how much history exists
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("cse-snapshot")

SERIES = PROJECT_ROOT / "data" / "cse" / "daily_closes.csv"
FIELDS = ("date", "symbol", "name", "close", "previous_close", "change_pct", "volume")

# Roughly a year of trading days. Below this a next-day model has nothing to
# learn from and would produce the kind of confident nonsense this replaced.
MIN_ROWS_PER_SYMBOL_TO_TRAIN = 250


def _existing_keys() -> set:
    """(date, symbol) already recorded, so re-running in a day is harmless."""
    if not SERIES.exists():
        return set()
    with SERIES.open(newline="", encoding="utf-8") as handle:
        return {(row["date"], row["symbol"]) for row in csv.DictReader(handle)}


def status() -> int:
    if not SERIES.exists():
        print(f"  no series yet at {SERIES}")
        return 0
    with SERIES.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    per_symbol: dict = {}
    for row in rows:
        per_symbol[row["symbol"]] = per_symbol.get(row["symbol"], 0) + 1
    days = len({row["date"] for row in rows})
    print(f"  {SERIES}")
    print(f"  rows={len(rows)}  symbols={len(per_symbol)}  distinct days={days}")
    ready = [s for s, n in per_symbol.items() if n >= MIN_ROWS_PER_SYMBOL_TO_TRAIN]
    print(f"  symbols with enough history to train ({MIN_ROWS_PER_SYMBOL_TO_TRAIN}+): "
          f"{len(ready)}")
    return 0


def append_today() -> int:
    from src.utils.utils import tool_cse_prices

    quotes = tool_cse_prices(limit=50)
    rows = quotes.get("stocks") or []
    if not rows:
        logger.warning("no quotes returned (status=%s); nothing appended",
                       quotes.get("scrape_status"))
        return 1

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    seen = _existing_keys()
    SERIES.parent.mkdir(parents=True, exist_ok=True)
    new = existing = 0

    write_header = not SERIES.exists()
    with SERIES.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if write_header:
            writer.writeheader()
        for quote in rows:
            symbol = quote.get("symbol")
            if not symbol:
                continue
            if (today, symbol) in seen:
                existing += 1
                continue
            writer.writerow({
                "date": today,
                "symbol": symbol,
                "name": quote.get("name"),
                "close": quote.get("price"),
                "previous_close": quote.get("previous_close"),
                "change_pct": quote.get("change_pct"),
                "volume": quote.get("volume"),
            })
            new += 1

    logger.info("appended %d rows for %s (%d already present) -> %s",
                new, today, existing, SERIES)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true",
                        help="report how much history exists, append nothing")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT.parent / ".env")
    except Exception:  # noqa: BLE001
        pass

    return status() if args.status else append_today()


if __name__ == "__main__":
    raise SystemExit(main())
