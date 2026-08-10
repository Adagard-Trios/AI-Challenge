"""
The README must not claim more than the code delivers.

The competition rules state that "deliberately misleading judges may result in
disqualification", and the README said **50+ data sources**. The measured
figure is 19 public sources (12 reachable on 6 Aug 2026) plus 4 social
platforms: 23.

That gap was not deception, it was drift -- a number written early and never
revisited. These tests exist because drift is the normal state of a README and
nothing else in the repo was checking.
"""

import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPO_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

README = REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


# --- the source count -------------------------------------------------------

def test_no_inflated_source_count(readme):
    """
    The specific claim that was wrong, and any restatement of it.

    Matches "50+ data sources", "60+ sources", "over 40 data sources" etc. so
    that inflating the number again fails here rather than in front of a judge.
    """
    # A sentence that disclaims the old number is not a claim of it. This test
    # bans overclaiming, and recording what the overclaim used to be is the
    # opposite of that -- so retractions are exempt by their wording.
    RETRACTION = ("earlier version", "was not accurate", "previously", "corrected")

    inflated = []
    for line in readme.splitlines():
        if any(marker in line.lower() for marker in RETRACTION):
            continue
        for count in re.findall(
            r"(?:over\s+|more than\s+)?(\d{2,})\s*\+?\s*(?:data\s+)?sources",
            line,
            re.IGNORECASE,
        ):
            if int(count) > 30:
                inflated.append((count, line.strip()[:90]))

    assert not inflated, (
        f"README claims {[n for n, _ in inflated]} sources: {[t for _, t in inflated]}. "
        f"The measured figure is 23 (19 public + 4 social). "
        f"Run scripts/check_sources.py."
    )


def test_the_claimed_count_matches_the_probe_list(readme):
    """
    The README table and check_sources.py must describe the same set. If a
    source is added to one and not the other, the published number is wrong
    again -- just in the other direction.
    """
    from scripts.check_sources import SOURCES

    claimed = re.search(r"\*\*(\d+)\s+sources are integrated:\s*(\d+)\s+public", readme)
    assert claimed, "README no longer states an integrated source count"

    total, public = int(claimed.group(1)), int(claimed.group(2))
    assert public == len(SOURCES), (
        f"README says {public} public sources, check_sources.py probes {len(SOURCES)}"
    )
    assert total == len(SOURCES) + 4, (
        f"README says {total} total; expected {len(SOURCES)} public + 4 social"
    )


def test_every_probed_source_appears_in_the_readme_table(readme):
    from scripts.check_sources import SOURCES

    missing = [label for label, _, _ in SOURCES if label not in readme]
    assert not missing, f"probed but undocumented: {missing}"


# --- ML claims --------------------------------------------------------------

def test_no_stock_forecast_is_claimed(readme):
    """
    There is no trained CSE model and there cannot be one yet.

    Yahoo Finance carries no Colombo Stock Exchange listing in any symbol
    format, so every ticker returned zero rows; cse.lk publishes current prices
    but no per-company history, so a series has to be accumulated first. The
    endpoint returns status="prices_only" with predictions=None.

    This replaces an older check that required weather and currency to be
    marked unavailable too. That was true of the 512 MB Render deployment and
    is no longer true of the API: it runs on a host with TensorFlow, and both
    models were retrained and verified serving. Stock is the claim that is
    still false, and it was reintroduced once already.
    """
    row = next((line for line in readme.splitlines()
                if "CSE" in line and "|" in line and "price" in line.lower()), None)
    assert row is not None, "the CSE row is missing from the capability table"

    lowered = row.lower()
    assert "no forecast" in lowered or "prices" in lowered, (
        f"the CSE row does not make clear it is prices rather than a forecast: "
        f"{row.strip()[:120]}"
    )
    assert "prediction" not in lowered.replace("no forecast", ""), (
        f"the CSE row still claims a prediction: {row.strip()[:120]}"
    )


def test_anomaly_detection_claim_matches_the_shipped_model(readme):
    """
    The README says anomaly detection is live in-process. That is only true
    while the MiniLM artifact and scikit-learn are both actually shipped.
    """
    assert "384-dim ONNX" in readme or "ONNX all-MiniLM" in readme, (
        "README does not state which embedding the shipped model uses"
    )

    requirements = (PROJECT_ROOT / "requirements-service.txt").read_text(encoding="utf-8")
    installed = [
        line.strip().split("=")[0].split(">")[0].strip()
        for line in requirements.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "scikit-learn" in installed, (
        "README claims live anomaly detection but sklearn is not in the "
        "deployed requirement set"
    )


# --- submission requirements ------------------------------------------------

def test_sdg_alignment_is_present(readme):
    """A scored criterion of the competition, and it was entirely absent."""
    assert "SDG" in readme, "no SDG alignment section"
    for goal in ("SDG 13", "SDG 11"):
        assert goal in readme, f"{goal} not named"


def test_a_problem_statement_exists(readme):
    assert re.search(r"##.*problem", readme, re.IGNORECASE), (
        "no problem statement -- the submission is judged on the problem it solves"
    )


def test_impact_is_measurable(readme):
    """
    "How does your app make the situation better? Define the metric of
    success." A stated metric, not an adjective.
    """
    assert "time-to-awareness" in readme.lower(), "no stated impact metric"


@pytest.mark.xfail(
    reason="Live URLs not yet filled in. Judges do not run the code locally, "
           "so this must pass before submission -- it reports XPASS once the "
           "Live Demo table carries real URLs.",
    strict=False,
)
def test_live_urls_are_present(readme):
    """
    "You must provide a live URL where the application functions as intended."

    Deliberately a real check rather than a comment, so the gap stays visible
    in every test run instead of being remembered.
    """
    demo = readme.split("## 🎯 The problem")[0]

    urls = re.findall(r"https://[^\s|)\]]+", demo)
    assert urls, "the Live Demo table contains no URL at all"
    assert any(
        "onrender.com" in u or "vercel.app" in u or "://" in u for u in urls
    ), f"no deployed URL in the Live Demo table: {urls}"
