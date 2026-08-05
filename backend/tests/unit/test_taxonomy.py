"""
Canonical names, and why they are the whole feature.

Relevance is a join: what an event mentions against what a business depends on.
If an event says "Port of Colombo" and a profile says "Colombo Port", the join
does not happen, the event ranks low, and the failure is invisible -- it looks
like a quiet news day. Under-matching is the silent-failure shape this codebase
keeps producing, moved one layer up.

So these tests are not about tidiness. Every pair below is a real way the same
thing gets written in Sri Lankan news copy.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- the join must not miss ------------------------------------------------

@pytest.mark.parametrize(
    "surface",
    ["Colombo Port", "Port of Colombo", "colombo port", "CMB",
     "Colombo Harbour", "Colombo harbor", "  COLOMBO  PORT  "],
)
def test_every_way_of_writing_colombo_port_is_one_entity(surface):
    from src.intelligence.taxonomy import canonicalise

    name, known = canonicalise(surface, "INFRASTRUCTURE")
    assert name == "Port of Colombo"
    assert known is True


@pytest.mark.parametrize(
    "surface,expected",
    [
        ("Gampaha District", "Gampaha"),
        ("gampaha", "Gampaha"),
        ("Moneragala", "Monaragala"),      # both spellings are in common use
        ("Nuwara-Eliya", "Nuwara Eliya"),
        ("nuwaraeliya", "Nuwara Eliya"),
        ("Amparai", "Ampara"),
        ("Trinco", "Trincomalee"),
    ],
)
def test_district_spellings_converge(surface, expected):
    from src.intelligence.taxonomy import canonicalise

    assert canonicalise(surface, "PLACE")[0] == expected


@pytest.mark.parametrize(
    "surface,expected",
    [
        ("garments", "apparel"),
        ("Textile", "apparel"),
        ("clothing", "apparel"),
        ("Ceylon Tea", "tea"),
        ("shipping", "logistics"),
        ("freight", "logistics"),
        ("BPO", "technology"),
    ],
)
def test_sector_synonyms_fold(surface, expected):
    """
    An apparel exporter should match an event about "garments" without having
    to guess which word the journalist used.
    """
    from src.intelligence.taxonomy import canonicalise

    assert canonicalise(surface, "SECTOR")[0] == expected


def test_all_25_districts_are_present():
    """A missing district is a business that can never be matched."""
    from src.intelligence.taxonomy import DISTRICTS

    assert len(DISTRICTS) == 25, f"expected 25 districts, have {len(DISTRICTS)}"


# --- unknown entities stay usable -----------------------------------------

def test_unknown_companies_still_converge_across_spellings():
    """
    Company names are the open tail -- no seed table can cover them. They must
    still normalise, or "Hayleys PLC" and "Hayleys" become two suppliers.
    """
    from src.intelligence.taxonomy import canonicalise

    forms = ["Hayleys PLC", "Hayleys", "  hayleys  limited ", "HAYLEYS Ltd"]
    resolved = {canonicalise(f, "ORG")[0] for f in forms}

    assert len(resolved) == 1, f"same company resolved to {resolved}"


def test_unknown_entities_are_flagged_as_unknown():
    """The caller weights a known district differently from a guessed company."""
    from src.intelligence.taxonomy import canonicalise

    assert canonicalise("Gampaha", "PLACE")[1] is True
    assert canonicalise("Some Startup", "ORG")[1] is False


# --- the batch path --------------------------------------------------------

def test_junk_is_dropped_not_stored():
    """
    Two-letter tokens are the single biggest source of false matches in a
    relevance join -- "SL" or "EU" would match half the corpus.
    """
    from src.intelligence.taxonomy import canonicalise_many

    out = canonicalise_many([
        {"type": "PLACE", "name": "SL", "role": "affected"},
        {"type": "ORG", "name": "", "role": "actor"},
        {"type": "NONSENSE", "name": "Colombo", "role": "affected"},
        {"type": "PLACE", "name": "Gampaha", "role": "affected"},
    ])

    assert [e["name"] for e in out] == ["Gampaha"]


def test_the_same_entity_twice_in_one_event_is_one_link():
    from src.intelligence.taxonomy import canonicalise_many

    out = canonicalise_many([
        {"type": "INFRASTRUCTURE", "name": "Colombo Port", "role": "affected"},
        {"type": "INFRASTRUCTURE", "name": "Port of Colombo", "role": "mentioned"},
    ])

    assert len(out) == 1


def test_an_unrecognised_role_falls_back_rather_than_failing():
    from src.intelligence.taxonomy import canonicalise_many

    out = canonicalise_many([
        {"type": "PLACE", "name": "Kandy", "role": "destroyed_by"},
    ])

    assert out[0]["role"] == "mentioned"


def test_the_surface_form_is_kept_for_debugging():
    """
    When a match looks wrong, the first question is what the model actually
    said. Keeping it costs nothing and saves a re-run.
    """
    from src.intelligence.taxonomy import canonicalise_many

    out = canonicalise_many([
        {"type": "SECTOR", "name": "garments", "role": "affected"},
    ])

    assert out[0]["name"] == "apparel"
    assert out[0]["surface_form"] == "garments"


def test_malformed_input_does_not_raise():
    """This runs inside the agent loop; it must never take a cycle down."""
    from src.intelligence.taxonomy import canonicalise_many

    assert canonicalise_many(None) == []
    assert canonicalise_many([None, "string", 42, {}]) == []


# --- the vocabulary is closed ---------------------------------------------

def test_entity_types_match_what_the_prompt_asks_for():
    """
    A type the prompt requests but the taxonomy rejects is silently dropped
    output -- the model does the work and nothing stores it.
    """
    from src.intelligence.taxonomy import ENTITY_TYPES

    prompt = (PROJECT_ROOT / "src" / "nodes" / "combinedAgentNode.py").read_text(
        encoding="utf-8"
    )
    for entity_type in ENTITY_TYPES:
        assert entity_type in prompt, (
            f"{entity_type} is accepted by the taxonomy but never requested"
        )
