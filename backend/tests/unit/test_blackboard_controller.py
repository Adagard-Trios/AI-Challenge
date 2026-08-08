"""
The scheduler, in shadow.

It computes what it WOULD run and records that; the existing fan-out still
collects everything. Two properties matter more than the rest, and both guard
against a failure this project has actually had.

STARVATION. Opportunistic control produces less data, not obviously smarter
data, and "the feed looks dead" is a failure here that has taken a while to
notice more than once. Every collector has a max_interval floor, so the worst
case degrades to a SLOWER FIXED SCHEDULE rather than to silence.

BUDGET. Groq's free tier is 8,000 tokens per minute and this project already
hits it -- HTTP 413 while summarising a gazette. A source whose estimate
exceeds the remaining window must be DEFERRED, NOT ATTEMPTED. Discovering the
limit by hitting it is the behaviour being replaced.

Mostly pure: BoardDigest is a plain dataclass, so the scheduling logic is
tested without a database at all.
"""

import sys
from datetime import timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _digest(**kwargs):
    from src.blackboard.knowledge_sources import BoardDigest, REGISTRY

    defaults = {
        "foci": [],
        "severity_by_domain": {},
        # Everything just ran, so nothing is overdue unless a test says so.
        "last_run": {name: 0.0 for name in REGISTRY},
        "tokens_remaining": 8000,
    }
    defaults.update(kwargs)
    return BoardDigest(**defaults)


# --- the starvation guarantee ------------------------------------------------

def test_a_quiet_board_still_runs_everything_eventually():
    """
    THE test against silence. With nothing on the board and nothing asking, a
    naive scheduler runs nothing forever and the feed dies. Every source must
    still be planned once it passes its max_interval.
    """
    from src.blackboard.knowledge_sources import REGISTRY, build_agenda

    digest = _digest(last_run={name: 1e9 for name in REGISTRY})  # never ran
    agenda = build_agenda(digest)

    assert len(agenda) == len(REGISTRY), (
        f"only {len(agenda)} of {len(REGISTRY)} sources planned on a quiet "
        f"board; the rest would never run"
    )


def test_an_overdue_source_outranks_a_permanently_hot_focus():
    """
    Two starvation mechanisms exist because one is not enough: the weighted
    term can be starved indefinitely by a focus that never cools -- a flood
    running for a week -- so anything past twice its max_interval is promoted
    regardless of score.
    """
    from src.blackboard.knowledge_sources import REGISTRY, build_agenda, is_starving

    digest = _digest(
        foci=[{"kind": "district", "value": "Ratnapura", "urgency": 1.0}],
        severity_by_domain={"meteorological": 1.0},
        last_run={name: 0.0 for name in REGISTRY} | {"econ.cse": 1e9},
    )
    agenda = build_agenda(digest)
    assert agenda, "nothing planned"
    assert agenda[0].ks_name == "econ.cse", (
        f"a starving source ranked below a hot focus: {agenda[0].ks_name}"
    )
    assert is_starving(digest, REGISTRY["econ.cse"])


def test_starvation_is_not_clamped():
    """
    Clamping it to 1.0 would let a maximal focus tie with a source three times
    overdue, and ties are decided arbitrarily.
    """
    from src.blackboard.knowledge_sources import priority

    assert priority(starvation=3.0) > priority(focus_urgency=1.0,
                                               domain_severity=1.0)


# --- the budget gate ---------------------------------------------------------

def test_an_llm_source_is_deferred_not_attempted_when_the_budget_is_short():
    """
    THE anti-413 test. Today the limit is discovered by hitting it; here a
    source whose estimate exceeds what is left is never planned.
    """
    from src.blackboard.knowledge_sources import build_agenda

    digest = _digest(severity_by_domain={"social": 0.9}, tokens_remaining=300)
    planned = {a.ks_name for a in build_agenda(digest)}

    assert not any(name.endswith(".summarise") for name in planned), (
        f"an LLM source was planned with 300 tokens left: {planned}"
    )


def test_the_same_source_runs_when_the_budget_allows():
    """The gate must not be a permanent refusal."""
    from src.blackboard.knowledge_sources import build_agenda

    digest = _digest(severity_by_domain={"social": 0.9}, tokens_remaining=8000)
    planned = {a.ks_name for a in build_agenda(digest)}
    assert any(name.endswith(".summarise") for name in planned)


def test_a_reserve_is_held_for_classification():
    """
    Classification is the call whose output the user actually sees. Without a
    reserve a chatty summariser starves the feed of the one LLM step that
    turns raw posts into intelligence.
    """
    from src.blackboard.controller import CLASSIFY_RESERVE

    assert 0 < CLASSIFY_RESERVE < 1


def test_an_unreachable_budget_counter_reports_zero_not_full(monkeypatch):
    """
    Assume spent rather than free. Planning against a budget we cannot verify
    is exactly how the 413s happened.
    """
    from src.blackboard import controller
    from src.runtime import redis_client

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")   # nothing there
    redis_client.reset()
    assert controller.tokens_remaining() == 0
    redis_client.reset()


# --- targeting ---------------------------------------------------------------

def test_a_flood_focus_targets_the_district_rather_than_a_fixed_list():
    """
    The whole point of the exercise. Today the meteorological node scrapes five
    hardcoded districts whether or not anything is flooding.
    """
    from src.blackboard.knowledge_sources import build_agenda

    digest = _digest(
        foci=[{"kind": "district", "value": "Ratnapura", "urgency": 0.95}],
        severity_by_domain={"meteorological": 0.9},
    )
    agenda = {a.ks_name: a for a in build_agenda(digest)}

    assert "met.district_social" in agenda
    assert agenda["met.district_social"].params.get("district") == ["Ratnapura"]


def test_a_flood_focus_also_reaches_the_political_domain():
    """
    The cross-domain chain that motivated the whole design: emergency orders
    follow floods, so a district focus should pull the gazette forward too.
    Nothing in the current fan-out can express that.
    """
    from src.blackboard.knowledge_sources import build_agenda

    digest = _digest(
        foci=[{"kind": "district", "value": "Ratnapura", "urgency": 0.95}])
    assert "pol.official_gazette" in {a.ks_name for a in build_agenda(digest)}


def test_nothing_is_planned_when_nothing_asks_and_nothing_is_overdue():
    """
    The saving. Otherwise this is a fixed schedule with extra steps.
    """
    from src.blackboard.knowledge_sources import build_agenda

    assert build_agenda(_digest()) == []


# --- robustness --------------------------------------------------------------

def test_a_broken_trigger_does_not_silence_the_agenda(monkeypatch):
    from src.blackboard import knowledge_sources as ks

    def explode(_digest):
        raise RuntimeError("bad trigger")

    original = ks.REGISTRY["econ.cse"]
    monkeypatch.setitem(ks.REGISTRY, "econ.cse",
                        ks.KnowledgeSource(
                            name=original.name, domain=original.domain,
                            est_tokens=0, min_interval=timedelta(minutes=1),
                            max_interval=timedelta(minutes=60),
                            trigger=explode))

    digest = _digest(last_run={name: 1e9 for name in ks.REGISTRY})
    agenda = build = ks.build_agenda(digest)
    assert len(agenda) == len(ks.REGISTRY) - 1


def test_triggers_perform_no_io():
    """
    trigger() reads a digest computed once per tick. Twenty-five sources each
    querying to decide whether to run would cost more than running them.
    """
    source = (PROJECT_ROOT / "src" / "blackboard" / "knowledge_sources.py"
              ).read_text(encoding="utf-8")
    for forbidden in ("session_scope", "requests.", "get_client(", ".invoke("):
        assert forbidden not in source, (
            f"knowledge_sources.py performs I/O ({forbidden!r}); triggers must "
            f"read only the digest"
        )


# --- multi-replica claim -----------------------------------------------------

def test_only_one_replica_gets_to_run_a_source(monkeypatch):
    """
    The controller runs in every replica that collects. Without a claim, three
    replicas each decide met.district_social is due and all three scrape it --
    the same class of mistake as the unshared pacing gate, and against social
    sources the same consequence.
    """
    import uuid

    from src.blackboard import controller
    from src.runtime import redis_client

    try:
        import redis

        redis.Redis.from_url("redis://localhost:6379/0",
                             socket_connect_timeout=2).ping()
    except Exception:
        pytest.skip("no Redis (docker compose up -d redis)")

    ks_name = f"test.ks.{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    redis_client.reset()
    assert controller.claim(ks_name, interval_seconds=30) is True

    redis_client.reset()      # a different replica
    assert controller.claim(ks_name, interval_seconds=30) is False, (
        "two replicas both claimed the same source"
    )
    redis_client.reset()


def test_the_claim_fails_open(monkeypatch):
    """
    Deliberately the OPPOSITE of the social pacing gate, and the difference
    matters: an unavailable claim costs a duplicated scrape, while an
    unavailable pacing gate costs a banned account. Refusing to collect at all
    because a coordination hint is down trades a real outage for a
    hypothetical duplicate.
    """
    from src.blackboard import controller
    from src.runtime import redis_client

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")   # nothing there
    redis_client.reset()
    assert controller.claim("anything", interval_seconds=30) is True
    redis_client.reset()


def test_a_single_process_needs_no_claim(monkeypatch):
    from src.blackboard import controller
    from src.runtime import redis_client

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset()
    assert controller.claim("anything", interval_seconds=30) is True
    redis_client.reset()


def test_shadow_mode_takes_no_claims():
    """
    Claiming in shadow would hold slots against a controller that executes
    nothing, and starve the real one if both were ever enabled at once.
    """
    import ast

    source = (PROJECT_ROOT / "src" / "blackboard" / "controller.py").read_text(
        encoding="utf-8")
    tick = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef) and n.name == "tick"
    )
    body = ast.get_source_segment(source, tick) or ""
    assert 'mode() == "active"' in body, (
        "tick() claims without checking the mode, so shadow would hold slots"
    )


def test_shadow_is_the_default():
    """
    Handing collection to an unproven scheduler by default would skip the
    entire point of the stage.
    """
    from src.blackboard import controller

    assert controller.mode() == "shadow"


def test_the_mode_switch_needs_no_redeploy(monkeypatch):
    """A switch that needs a deploy is not one you can use at 2am."""
    from src.blackboard import controller

    monkeypatch.setenv("BLACKBOARD_CONTROL", "active")
    assert controller.mode() == "active"
    monkeypatch.setenv("BLACKBOARD_CONTROL", "nonsense")
    assert controller.mode() == "shadow", "an unknown mode must fail safe"
