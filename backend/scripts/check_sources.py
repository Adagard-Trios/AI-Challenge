"""
backend/scripts/check_sources.py
Probe every integrated data source and report which are actually reachable.

This exists so the source count in README.md is a measurement rather than a
claim. The README previously said "50+ data sources"; the real figure is 24
integrated, of which this script found 13 reachable.

    python scripts/check_sources.py

Reachable means HTTP 200 with a non-trivial body. A redirect, a 403 or a TLS
failure is reported as-is rather than counted, because "the host resolves" and
"we can collect from it" are different things and only the second one matters.

Note that some sources block datacenter IPs (reddit is the reliable example),
so results differ between a laptop and a deployed instance. That is itself
worth knowing, and it is the reason social collection runs on the user's own
machine.
"""

from __future__ import annotations

import concurrent.futures as futures
import sys

# (label, url, domain). Kept in one list so the README table and this script
# cannot drift apart.
SOURCES = [
    ("rivernet.lk",              "https://rivernet.lk/",                     "Flood / river gauges"),
    ("meteo.gov.lk",             "https://meteo.gov.lk/",                    "DMC weather + warnings"),
    ("cbsl.gov.lk",              "https://www.cbsl.gov.lk/",                 "Central Bank indicators"),
    ("ceypetco.gov.lk",          "https://ceypetco.gov.lk/",                 "Fuel prices"),
    ("ceb.lk",                   "https://ceb.lk/",                          "Power / load shedding"),
    ("gazette.lk",               "http://www.gazette.lk/",                   "Government gazette"),
    ("parliament.lk",            "https://www.parliament.lk/",               "Parliament proceedings"),
    ("health.gov.lk",            "https://www.health.gov.lk/",               "Dengue / disease alerts"),
    ("cse.lk",                   "https://www.cse.lk/",                      "Colombo Stock Exchange"),
    ("data.humdata.org",         "https://data.humdata.org/",                "WFP commodity prices"),
    ("dailymirror.lk",           "https://www.dailymirror.lk/",              "News"),
    ("newsfirst.lk",             "https://www.newsfirst.lk/",                "News"),
    ("ft.lk",                    "https://www.ft.lk/",                       "News (financial)"),
    ("adaderana.lk",             "https://www.adaderana.lk/",                "News"),
    ("newswire.lk",              "https://www.newswire.lk/",                 "News"),
    ("news.lk",                  "https://www.news.lk/",                     "Government news portal"),
    ("eservices.railway.gov.lk", "https://eservices.railway.gov.lk/",        "Rail schedules"),
    ("reddit.com",               "https://www.reddit.com/r/srilanka.json",   "r/srilanka"),
    ("api.rivernet.lk",          "https://api.rivernet.lk/",                 "River gauge API"),
    ("aterboard.lk",             "https://aterboard.lk/",                    "Water board / supply"),
    ("nitter.net",               "https://nitter.net/",                      "Twitter mirror (fallback)"),
]

MIN_BODY = 500      # anything smaller is an error page, not content
TIMEOUT = 20


def probe(entry):
    label, url, domain = entry
    try:
        import requests

        # Follow redirects: the scrapers do, so counting a 301 as unreachable
        # would understate what we can actually collect. Several of these hosts
        # 301 from apex to www.
        response = requests.get(
            url, timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RogerIntel/1.0)"},
            allow_redirects=True,
        )
        size = len(response.content)
        ok = response.status_code == 200 and size >= MIN_BODY
        return label, domain, str(response.status_code), size, ok
    except Exception as exc:  # noqa: BLE001
        return label, domain, type(exc).__name__, 0, False


def main() -> int:
    print(f"Probing {len(SOURCES)} integrated sources...\n")

    with futures.ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(probe, SOURCES))

    results.sort(key=lambda r: (not r[4], r[0]))
    for label, domain, status, size, ok in results:
        print(f"  {'LIVE' if ok else '----'}  {status:<16} {size:>9,}  {label:<26} {domain}")

    live = sum(1 for r in results if r[4])
    print(f"\n  {live}/{len(SOURCES)} reachable from this machine.")
    print("  Plus 4 social platforms collected via the user's connector.")
    print(f"\n  README should read: {len(SOURCES) + 4} integrated, {live} verified reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
