"""
The economic data parsers, pinned against captured source text.

Every one of these tools was serving hardcoded constants while reporting no
error. Measured on 2026-08-05, before the repair:

    inflation   dashboard 2.1 %    actual 7.3 %    (3.5x understated)
    policy rate dashboard 7.75 %   actual 8.75 %
    USD/LKR     dashboard 309.12   actual 335.39
    petrol 92   dashboard Rs.294   actual Rs.414   (40 % understated)

None of the sources were down. CBSL returned HTTP 200 with the numbers present
in the page text; the patterns looked for a data widget that does not exist.
CEYPETCO publishes an authoritative table and the old code instead trawled three
news homepages for any number adjacent to the word "petrol".

The fixtures below are real captured text. They keep this honest offline: if a
pattern is loosened until it matches the wrong number, these fail.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# Captured from cbsl.gov.lk, 2026-08-05. CBSL states its headline figures as
# prose in the press releases carried on the homepage.
CBSL_TEXT = (
    "Consumer Price Index (CCPI, 2021=100) based headline inflation "
    "(year-on-year, Y-o-Y) increased to 7.3% in July 2026 from 6.8% in June "
    "2026, primarily reflecting the monthly increase in prices of items in the "
    "food category and the base effect in food inflation. Meanwhile, food "
    "inflation (Y-o-Y) accelerated to 6.3% in July 2026 from 3.6% in June 2026, "
    "contributing mainly to this increase. The Monetary Policy Board, at its "
    "meeting held yesterday, decided to maintain the Overnight Policy Rate "
    "(OPR) at the current level of 8.75%. The Board arrived at this decision "
    "following a careful analysis."
)

# Captured from ceypetco.gov.lk/marketing-sales/, 2026-08-05, as flattened by
# BeautifulSoup.get_text("|"). Products are cards, not a table.
CEYPETCO_TEXT = (
    "White Oil|Lanka Petrol 92 Octane|White Oil|Rs.|414.00|per Ltr|"
    "\U0001f4c5|Effect from: 29-06-2026 12.00 Midnight|"
    "Lanka Auto Diesel|White Oil|Rs.|382.00|per Ltr|"
    "\U0001f4c5|Effect from: 29-06-2026 12.00 Midnight|"
    "Lanka Kerosene|White Oil|Rs.|285.00|per Ltr|"
    "\U0001f4c5|Effect from: 30-05-2026 12.00 Midnight|"
    "Lanka Petrol 95 Octane Euro 4|White Oil|Rs.|495.00|per Ltr|"
    "\U0001f4c5|Effect from: 30-05-2026 12.00 Midnight|"
    "Lanka Super Diesel 4 Star Euro 4|White Oil|Rs.|478.00|per Ltr|"
    "\U0001f4c5|Effect from: 30-05-2026 12.00 Midnight|"
    "Lanka Industrial Kerosene|White Oil|Rs.|434.00|per Ltr|"
    "\U0001f4c5|Effect from: 01-04-2026 12.00 Midnight"
)


# --- CBSL ------------------------------------------------------------------

def test_ccpi_inflation_is_parsed_with_its_period():
    from src.utils.utils import CBSL_CCPI_RE

    m = CBSL_CCPI_RE.search(CBSL_TEXT)
    assert m, "headline CCPI inflation no longer matches"
    assert float(m.group(1)) == 7.3
    assert m.group(2) == "July 2026", (
        "the period must come from the release, not from today's date -- the "
        "old code stamped utc_now() even on baseline values"
    )


def test_food_inflation_is_not_mistaken_for_headline():
    """
    Both sentences say 'inflation ... to X% in July 2026'. A loose pattern
    grabs 6.3 (food) for the headline figure, or vice versa.
    """
    from src.utils.utils import CBSL_CCPI_RE, CBSL_FOOD_RE

    assert float(CBSL_CCPI_RE.search(CBSL_TEXT).group(1)) == 7.3
    assert float(CBSL_FOOD_RE.search(CBSL_TEXT).group(1)) == 6.3


def test_policy_rate_parsed_from_a_hold_decision():
    from src.utils.utils import CBSL_OPR_RE

    m = CBSL_OPR_RE.search(CBSL_TEXT)
    assert m, "OPR no longer matches"
    assert float(m.group(1)) == 8.75


def test_policy_rate_parsed_from_a_cut_decision():
    """CBSL alternates between 'maintain ... at' and 'reduce ... to'."""
    from src.utils.utils import CBSL_OPR_RE

    text = (
        "The Monetary Policy Board decided to reduce the Overnight Policy Rate "
        "(OPR) to 7.50%. The Board noted."
    )
    assert float(CBSL_OPR_RE.search(text).group(1)) == 7.50


def test_patterns_do_not_match_unrelated_prose():
    """A page with no figures must yield nothing, not a spurious number."""
    from src.utils.utils import CBSL_CCPI_RE, CBSL_OPR_RE

    text = (
        "The Central Bank published its Annual Report. Inflation remains a "
        "focus. The Overnight Policy Rate is reviewed every six weeks."
    )
    assert CBSL_CCPI_RE.search(text) is None
    assert CBSL_OPR_RE.search(text) is None


@pytest.mark.parametrize(
    "kind,value,ok",
    [
        ("inflation", 7.3, True), ("inflation", 65.0, True),
        ("inflation", 2021.0, False), ("inflation", -50.0, False),
        ("policy_rate", 8.75, True), ("policy_rate", 2026.0, False),
        ("usd_lkr", 335.39, True), ("usd_lkr", 2.0, False),
    ],
)
def test_range_check_rejects_implausible_values(kind, value, ok):
    """
    A drifting regex usually lands on a year or an index base (2021=100). The
    range check is what stops a wrong-but-formatted number reaching a dashboard.
    """
    from src.utils.utils import _cbsl_in_range

    assert _cbsl_in_range(kind, value) is ok


# --- CEYPETCO --------------------------------------------------------------

def test_all_fuel_products_are_parsed():
    from src.utils.utils import CEYPETCO_ROW_RE, _fuel_key

    found = {}
    for m in CEYPETCO_ROW_RE.finditer(CEYPETCO_TEXT):
        key = _fuel_key(m.group(1))
        if key:
            found[key] = float(m.group(2))

    assert found == {
        "petrol_92": 414.00,
        "petrol_95": 495.00,
        "auto_diesel": 382.00,
        "super_diesel": 478.00,
        "kerosene": 285.00,
        "industrial_kerosene": 434.00,
    }


def test_longer_product_names_win_over_shorter_ones():
    """
    'Lanka Industrial Kerosene' must not be filed as plain kerosene, and
    'Petrol 95' must not be filed as 'Petrol 92'. Ordering in
    FUEL_KEY_PATTERNS is what guarantees this.
    """
    from src.utils.utils import _fuel_key

    assert _fuel_key("Lanka Industrial Kerosene") == "industrial_kerosene"
    assert _fuel_key("Lanka Kerosene") == "kerosene"
    assert _fuel_key("Lanka Petrol 95 Octane Euro 4") == "petrol_95"
    assert _fuel_key("Lanka Petrol 92 Octane") == "petrol_92"
    assert _fuel_key("Lanka Super Diesel 4 Star Euro 4") == "super_diesel"
    assert _fuel_key("Lanka Auto Diesel") == "auto_diesel"


def test_unknown_products_are_skipped_not_guessed():
    from src.utils.utils import _fuel_key

    assert _fuel_key("Lanka Bitumen") is None
    assert _fuel_key("Some New Product") is None


def test_effective_dates_sort_chronologically():
    """last_revision is the newest 'Effect from', not the first one matched."""
    from src.utils.utils import _fuel_date_key

    dates = ["01-04-2026", "29-06-2026", "30-05-2026"]
    assert max(dates, key=_fuel_date_key) == "29-06-2026"
    assert _fuel_date_key("garbage") == (0, 0, 0)


# --- CEB -------------------------------------------------------------------

def test_ceb_never_claims_the_grid_is_healthy_without_evidence():
    """
    REGRESSION, and the worst of the set. A failed scrape returned
    status="no_load_shedding", load_shedding_active=False and announced
    "CEB: Normal power supply across the island" -- an affirmative claim about
    the national grid made without having read anything. During actual load
    shedding that is exactly backwards.
    """
    src = (PROJECT_ROOT / "src" / "utils" / "utils.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )

    assert "Normal power supply across the island" not in code
    assert '"status": "operational"' not in code, (
        "CEB must start from unknown, not from a healthy assumption"
    )
    assert '"load_shedding_active": None' in code
