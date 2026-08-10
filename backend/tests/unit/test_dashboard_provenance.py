"""
Every source-data card must show where its numbers came from.

The bug this prevents is subtle and was live for the whole project's history:
cards rendered a "LIVE" badge when scrape_status was "live", and rendered
*nothing* otherwise. Stale data was therefore signalled by the ABSENCE of a
badge -- which nobody notices. A hardcoded 2.1 % inflation figure sat next to a
policy rate a full point out and a USD/LKR rate off by 8 %, all looking exactly
as authoritative as the live commodity prices beside them.

So it is not enough for a card to read scrape_status. It must render something
on the non-live path, which is what DataProvenance guarantees.
"""

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPO_ROOT = PROJECT_ROOT.parent
CARDS = REPO_ROOT / "frontend" / "app" / "components" / "dashboard"

# Cards backed by a scraped public source. Prediction cards carry model
# staleness instead, and derived cards (overview, trending) inherit it.
SOURCE_CARDS = [
    "EconomicIndicators.tsx",
    "FuelPriceMonitor.tsx",
    "CommodityPrices.tsx",
    "PowerOutageStatus.tsx",
    "WaterSupplyStatus.tsx",
    "HealthAlerts.tsx",
    "RiverNetStatus.tsx",
]

pytestmark = pytest.mark.skipif(
    not CARDS.exists(), reason="frontend not present"
)


@pytest.mark.parametrize("card", SOURCE_CARDS)
def test_card_renders_provenance(card):
    path = CARDS / card
    assert path.exists(), f"{card} is gone"

    src = path.read_text(encoding="utf-8")
    assert "DataProvenance" in src, (
        f"{card} does not render DataProvenance, so a reader cannot tell "
        "whether its numbers are live or a hardcoded fallback"
    )


@pytest.mark.parametrize("card", SOURCE_CARDS)
def test_card_does_not_badge_only_the_live_case(card):
    """
    REGRESSION. `{scrapeStatus === "live" && <Badge>LIVE</Badge>}` renders
    nothing at all when the data is stale. The condition has to have an else,
    or go through DataProvenance, which always renders.
    """
    src = (CARDS / card).read_text(encoding="utf-8")

    # A `&&` guard on a live check with no ternary is the dangerous shape.
    offenders = re.findall(
        r'scrapeStatus\s*===\s*"live"\s*&&', src
    )
    assert not offenders, (
        f"{card} renders a badge only when live; stale data shows no badge at "
        "all, which reads as normal"
    )


def test_the_shared_component_treats_missing_status_as_unknown():
    """
    An absent scrape_status must not fall through to 'live'. A tool that
    forgets to report provenance should look suspicious, not authoritative.
    """
    src = (CARDS / "DataProvenance.tsx").read_text(encoding="utf-8")

    assert '"unavailable"' in src
    assert re.search(r'status\s+in\s+config\s*\?\s*status\s*:\s*"unavailable"', src), (
        "DataProvenance must default an unknown/missing status to 'unavailable'"
    )


def test_every_status_the_backend_can_emit_is_renderable():
    """The UI switches on this vocabulary; a gap renders as a blank badge."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.utils.utils import PROVENANCE_STATUSES

    src = (CARDS / "DataProvenance.tsx").read_text(encoding="utf-8")

    for status in PROVENANCE_STATUSES:
        assert re.search(rf"\b{status}:\s*\{{", src), (
            f"DataProvenance has no rendering for status {status!r}, which the "
            "backend can return"
        )
