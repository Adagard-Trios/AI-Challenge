"""
Relevance scoring: does this event matter to THIS business?

Relevance decides what a user sees first, so it is the part they will argue
with. Two properties make that argument possible, and both are tested here:

  - it is pure, so the same inputs always give the same answer
  - it explains itself, so "why is this ranked above that" has a real answer

The failure mode to guard hardest against is not a wrong score. It is scoring
when there is nothing to score against: a user with no profile must get the
feed unranked, never a feed scored entirely zero, because "nothing today
concerns you" and "we have no idea what concerns you" look identical on screen
and only one of them is true.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


APPAREL_EXPORTER = {
    "districts": ["Gampaha", "Kandy"],
    "infrastructure": ["Port of Colombo"],
    "sectors": ["apparel"],
    "suppliers": ["Hayleys"],
    "lanes": ["Colombo-Singapore"],
    "keywords": ["tariff"],
}


def exposure(**overrides):
    from src.intelligence.relevance import Exposure

    return Exposure.from_profile({**APPAREL_EXPORTER, **overrides})


def entity(etype, name, role="affected", known=True):
    return {"type": etype, "name": name, "role": role, "known": known}


# --- the no-profile rule ---------------------------------------------------

def test_no_profile_returns_none_not_zero():
    """
    THE important distinction. None means "not scored"; 0.0 means "scored, and
    this does not touch you". Collapsing them would let an unconfigured account
    see a feed that looks entirely irrelevant.
    """
    from src.intelligence.relevance import Exposure, score_event

    assert score_event([entity("PLACE", "Gampaha")], Exposure.empty()) is None
    assert score_event([entity("PLACE", "Gampaha")], None) is None


def test_a_scored_miss_is_zero_not_none():
    from src.intelligence.relevance import score_event

    result = score_event([entity("PLACE", "Jaffna")], exposure())
    assert result is not None
    assert result.score == 0.0
    assert result.matched_on == ()


def test_the_filter_keeps_everything_when_nothing_is_scored():
    """The platform must never hide an event because the user has not configured."""
    from src.intelligence.relevance import is_relevant

    assert is_relevant(None) is True


# --- weighting -------------------------------------------------------------

@pytest.mark.parametrize(
    "ent,expected_at_least,label",
    [
        (entity("ORG", "Hayleys", known=False), 0.80, "a named supplier"),
        (entity("INFRASTRUCTURE", "Port of Colombo"), 0.80, "your port"),
        (entity("PLACE", "Gampaha"), 0.75, "your district"),
        (entity("SECTOR", "apparel"), 0.40, "your sector"),
    ],
)
def test_specific_matches_outrank_general_ones(ent, expected_at_least, label):
    from src.intelligence.relevance import score_event

    result = score_event([ent], exposure())
    assert result.score >= expected_at_least, f"{label} scored {result.score}"


def test_a_named_supplier_outranks_the_whole_sector():
    """
    "Your supplier had a fire" must beat "the apparel sector had a good
    quarter". Anything else buries the specific under the general.
    """
    from src.intelligence.relevance import score_event

    supplier = score_event([entity("ORG", "Hayleys", known=False)], exposure())
    sector = score_event([entity("SECTOR", "apparel")], exposure())

    assert supplier.score > sector.score


def test_being_affected_outranks_being_merely_mentioned():
    """Your district flooding is not your district's council passing a bylaw."""
    from src.intelligence.relevance import score_event

    affected = score_event([entity("PLACE", "Gampaha", role="affected")], exposure())
    actor = score_event([entity("PLACE", "Gampaha", role="actor")], exposure())
    mentioned = score_event([entity("PLACE", "Gampaha", role="mentioned")], exposure())

    assert affected.score > actor.score > mentioned.score


def test_the_score_is_the_best_match_not_a_sum():
    """
    Summing lets a noisy extractor inflate anything: five weak sector hits
    would outrank one named supplier.
    """
    from src.intelligence.relevance import score_event, WEIGHTS

    many_weak = score_event(
        [entity("SECTOR", "apparel", role="mentioned")] * 5, exposure()
    )
    assert many_weak.score < WEIGHTS["supplier"]


def test_multiple_distinct_matches_add_a_capped_bonus():
    """
    Corroboration across different exposure fields is real signal, but the
    bonus must never lift a sector-only match past an infrastructure one --
    the weight ordering is a product decision, not something arithmetic
    overturns.
    """
    from src.intelligence.relevance import score_event

    one = score_event([entity("PLACE", "Gampaha")], exposure())
    several = score_event(
        [
            entity("PLACE", "Gampaha"),
            entity("INFRASTRUCTURE", "Port of Colombo"),
            entity("SECTOR", "apparel"),
        ],
        exposure(),
    )

    assert several.score > one.score
    assert several.score <= 1.0


def test_an_unknown_entity_is_discounted_but_not_discarded():
    """
    Company names are the extractor's guess. Supplier matching depends on them,
    so they must count -- just not outrank a known district.
    """
    from src.intelligence.relevance import score_event

    known = score_event([entity("ORG", "Hayleys", known=True)], exposure())
    guessed = score_event([entity("ORG", "Hayleys", known=False)], exposure())

    assert guessed.score < known.score
    assert guessed.score > 0.0


# --- explanations ----------------------------------------------------------

def test_every_score_explains_itself():
    """
    A number with authority and no accountability is the
    `compliance_volatility: 0.7` problem again.
    """
    from src.intelligence.relevance import score_event

    result = score_event(
        [entity("PLACE", "Gampaha"), entity("INFRASTRUCTURE", "Port of Colombo")],
        exposure(),
    )

    assert result.matched_on, "a non-zero score with no explanation"
    assert len(result.matched_on) == 2
    assert any("Gampaha" in reason for reason in result.matched_on)


def test_explanations_are_written_for_a_reader():
    from src.intelligence.relevance import score_event

    result = score_event([entity("PLACE", "Gampaha")], exposure())
    assert result.matched_on[0] == "your Gampaha operations"

    result = score_event([entity("ORG", "Hayleys", known=False)], exposure())
    assert result.matched_on[0] == "your supplier Hayleys"


def test_explanations_use_the_users_own_spelling():
    """
    The badge should echo what the user typed, not the canonical form, or it
    reads as though the platform corrected them.
    """
    from src.intelligence.relevance import Exposure, score_event

    exp = Exposure.from_profile({"suppliers": ["MAS Holdings"]})
    result = score_event([entity("ORG", "mas holdings", known=False)], exp)

    assert "MAS Holdings" in result.matched_on[0]


# --- canonicalisation across the join -------------------------------------

def test_the_join_survives_different_spellings():
    """
    The whole reason taxonomy.py exists. A profile saying "Colombo Port" and an
    event saying "Port of Colombo" must meet -- the API canonicalises on write,
    so by the time it reaches here both sides are canonical.
    """
    from src.intelligence.relevance import Exposure, score_event
    from src.intelligence.taxonomy import canonicalise

    stored, _ = canonicalise("Colombo Port", "INFRASTRUCTURE")
    exp = Exposure.from_profile({"infrastructure": [stored]})

    result = score_event([entity("INFRASTRUCTURE", "Port of Colombo")], exp)
    assert result.score > 0.0


def test_matching_ignores_case_and_spacing():
    from src.intelligence.relevance import Exposure, score_event

    exp = Exposure.from_profile({"districts": ["  GAMPAHA  "]})
    result = score_event([entity("PLACE", "gampaha")], exp)
    assert result.score > 0.0


# --- keywords --------------------------------------------------------------

def test_keywords_match_the_summary_not_the_entities():
    """Keywords exist precisely for what the taxonomy does not model."""
    from src.intelligence.relevance import score_event

    result = score_event([], exposure(), summary="New import tariff schedule announced")

    assert result.score > 0.0
    assert "tariff" in result.matched_on[0]


def test_a_users_own_keyword_clears_the_relevance_bar():
    """
    They typed it because they care. A threshold above the keyword weight would
    mean an explicit keyword match never counted as relevant.
    """
    from src.intelligence.relevance import is_relevant, score_event

    result = score_event([], exposure(), summary="A new tariff was announced today")
    assert is_relevant(result) is True


def test_a_passing_sector_mention_does_not_clear_the_bar():
    """The filter has to actually filter something."""
    from src.intelligence.relevance import is_relevant, score_event

    result = score_event(
        [entity("SECTOR", "apparel", role="mentioned")], exposure()
    )
    assert result.score > 0.0
    assert is_relevant(result) is False


# --- robustness ------------------------------------------------------------

def test_malformed_entities_do_not_raise():
    """This runs per event on every feed request."""
    from src.intelligence.relevance import score_event

    result = score_event(
        [None, "string", 42, {}, {"type": "PLACE"}, {"name": "Gampaha"}],
        exposure(),
    )
    assert result is not None


def test_an_exposure_of_only_blanks_counts_as_empty():
    """Whitespace in a form field must not silently enable scoring."""
    from src.intelligence.relevance import Exposure

    exp = Exposure.from_profile({"districts": ["", "   ", None]})
    assert exp.is_empty()


# --- the feed layer --------------------------------------------------------

def test_annotate_leaves_the_feed_alone_when_there_is_no_exposure():
    from src.intelligence.feed_relevance import annotate

    events = [
        {"event_id": "a", "summary": "first"},
        {"event_id": "b", "summary": "second"},
    ]
    out = annotate(events, None)

    assert [e["event_id"] for e in out] == ["a", "b"], "order changed"
    assert all(e["relevance"] is None for e in out)


def test_annotate_sorts_by_relevance():
    from src.intelligence.feed_relevance import annotate

    events = [
        {"event_id": "far", "summary": "x", "entities": [entity("PLACE", "Jaffna")]},
        {"event_id": "near", "summary": "y",
         "entities": [entity("INFRASTRUCTURE", "Port of Colombo")]},
    ]
    out = annotate(events, exposure())

    assert out[0]["event_id"] == "near"


def test_the_filter_never_returns_an_empty_feed():
    """
    A blank page reads as "no news". If the filter would empty the feed, show
    everything and let the badges explain instead.
    """
    from src.intelligence.feed_relevance import annotate

    events = [
        {"event_id": "a", "summary": "x", "entities": [entity("PLACE", "Jaffna")]},
    ]
    out = annotate(events, exposure(), only_relevant=True)

    assert out, "the filter emptied the feed"


def test_annotate_does_not_mutate_the_caller_s_events():
    """
    REGRESSION, found end-to-end. /api/feed serves
    current_state["final_ranked_feed"] -- global, shared across requests, and
    broadcast over the websocket. Writing `relevance` onto those dicts in place
    stamped one user's exposure matches onto the state every other user reads,
    and sorting in place reordered the global feed to suit whoever asked last.
    """
    from src.intelligence.feed_relevance import annotate

    original = [
        {"event_id": "a", "summary": "x", "entities": [entity("PLACE", "Jaffna")]},
        {"event_id": "b", "summary": "y",
         "entities": [entity("INFRASTRUCTURE", "Port of Colombo")]},
    ]
    snapshot = [dict(e) for e in original]

    out = annotate(original, exposure())

    assert out[0]["event_id"] == "b", "the copy was not ranked"
    assert [e["event_id"] for e in original] == ["a", "b"], "caller's list reordered"
    assert all("relevance" not in e for e in original), (
        "relevance was written onto the caller's event dicts"
    )
    assert original == snapshot


def test_the_postgres_store_imports_the_real_session_factory():
    """
    REGRESSION. PostgresEntityStore imported `SessionLocal`, which auth.db does
    not export -- it exposes session_factory(). The import raised,
    get_entity_store() caught it, and every write silently went to
    NullEntityStore. The feature would have looked implemented and stored
    nothing.
    """
    import inspect

    from src.intelligence import entity_store

    raw = inspect.getsource(entity_store.PostgresEntityStore.__init__)
    # Strip comments: the one explaining this very bug names the old symbol.
    source = "\n".join(
        line for line in raw.splitlines() if not line.strip().startswith("#")
    )

    assert "session_factory" in source
    assert "SessionLocal" not in source

    import auth.db

    assert hasattr(auth.db, "session_factory")


# --- entity chips survive a page reload -------------------------------------

def test_entities_are_hydrated_even_without_an_exposure_profile():
    """
    REGRESSION. /api/feeds rebuilds events from the database through a field
    whitelist, and entities do not live in that row -- they are in the entity
    store. So the same event showed entity chips when it arrived over the
    websocket and none after a page reload, which is exactly the inconsistency
    the whitelist comment in main.py already describes for region and
    fake_news_score.

    Hydration deliberately runs before the exposure check: chips are "what is
    this event about", which is worth showing whether or not a profile exists.
    """
    from src.intelligence import feed_relevance

    class FakeStore:
        def entities_for(self, ids):
            return {"e2": [{"type": "PLACE", "name": "Port of Colombo",
                            "role": "affected"}]}

    # _entities_for imports get_entity_store inside the function, so the patch
    # has to land on the source module rather than on feed_relevance.
    from src.intelligence import entity_store as entity_store_module

    original = entity_store_module.get_entity_store
    entity_store_module.get_entity_store = lambda: FakeStore()
    try:
        events = [
            {"event_id": "e1", "summary": "has them inline",
             "entities": [{"type": "PLACE", "name": "Kandy", "role": "affected"}]},
            {"event_id": "e2", "summary": "only in the store"},
            {"event_id": "e3", "summary": "genuinely names nothing"},
        ]
        out = feed_relevance.annotate(events, None)   # no profile at all
    finally:
        entity_store_module.get_entity_store = original

    by_id = {e["event_id"]: e for e in out}
    assert [x["name"] for x in by_id["e1"]["entities"]] == ["Kandy"]
    assert [x["name"] for x in by_id["e2"]["entities"]] == ["Port of Colombo"]
    assert by_id["e2"]["entities_extracted"] is True
    assert not by_id["e3"].get("entities")

    # And the shared feed dicts must still not be written through.
    assert "entities" not in events[1], "annotate mutated the caller's event"


def test_the_feeds_endpoint_carries_entities_through_its_whitelist():
    """
    The whitelist is explicit, so a new field is dropped unless someone adds
    it. That has now happened twice; this is the guard.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).parent.parent.parent / "main.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)

    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "get_feeds_from_db"
    )
    body = ast.get_source_segment(source, fn) or ""

    for field in ("entities", "entities_extracted", "region",
                  "fake_news_score", "llm_filtered"):
        assert f'"{field}"' in body, (
            f"the /api/feeds whitelist drops {field!r}, so it is present on the "
            "live websocket feed and absent after a page reload"
        )


def test_events_are_stored_with_their_entities():
    """
    store_event() accepts entities and links them for relevance scoring. The
    graph-streaming call site did not pass them, so events stored on that path
    were invisible to a user's exposure profile.
    """
    import ast
    from pathlib import Path

    source = (Path(__file__).parent.parent.parent / "main.py").read_text(
        encoding="utf-8")

    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "store_event"
    ]
    assert calls, "no store_event call found in main.py"

    for call in calls:
        keywords = {kw.arg for kw in call.keywords}
        assert "entities" in keywords, (
            "a store_event call omits entities, so relevance scoring has "
            "nothing to join a user's exposure against"
        )
