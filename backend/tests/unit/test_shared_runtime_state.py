"""
State that must be shared once there is more than one replica.

Two pieces here, both of which were correct only by virtue of a single process:

  auth/ws_tickets.py   in-process dict of WebSocket tickets
  main.py              seen_event_ids: an unbounded, per-process set

The ticket one is the hard blocker for running replicas at all, and it fails in
a way that does not look like an auth bug. The two halves of the handshake are
separate connections:

    POST /api/auth/ws-ticket   ->  api-1
    new WebSocket(?ticket=)    ->  api-3

so with N replicas roughly (N-1)/N of connections are rejected with code 1008.
The user sees "the dashboard keeps disconnecting". ws_tickets.py predicted this
in its own docstring and said "Move them to Redis".

Redis tests skip when Redis is absent; the in-process fallbacks are asserted
unconditionally, so the behaviour that runs on a laptop is always covered.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def _needs_redis():
    try:
        import redis
    except ImportError:  # pragma: no cover
        pytest.skip("redis package not installed")
    try:
        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2).ping()
    except Exception:
        pytest.skip(f"no Redis at {REDIS_URL} (docker compose up -d redis)")


def _as_new_process(monkeypatch, url=REDIS_URL):
    """Simulate a different replica: fresh client, same Redis."""
    from src.runtime import redis_client

    monkeypatch.setenv("REDIS_URL", url)
    redis_client.reset()


# --- WebSocket tickets ------------------------------------------------------

def test_a_ticket_issued_on_one_replica_is_redeemable_on_another(monkeypatch):
    """
    THE blocker. Without this, WebSocket auth fails for (N-1)/N connections and
    presents as flakiness rather than as an auth failure.
    """
    _needs_redis()
    from auth import ws_tickets

    _as_new_process(monkeypatch)
    ticket = ws_tickets.issue("user-abc")
    ws_tickets.clear()          # replica 1's memory is gone

    _as_new_process(monkeypatch)   # replica 2
    assert ws_tickets.redeem(ticket) == "user-abc", (
        "a ticket issued by one replica is invisible to another"
    )


def test_a_shared_ticket_is_still_single_use(monkeypatch):
    """
    Redemption must be atomic. GET then DELETE lets two connections racing the
    same ticket both read it before either deletes, and both authenticate.
    """
    _needs_redis()
    from auth import ws_tickets

    _as_new_process(monkeypatch)
    ticket = ws_tickets.issue("user-xyz")

    _as_new_process(monkeypatch)
    assert ws_tickets.redeem(ticket) == "user-xyz"
    assert ws_tickets.redeem(ticket) is None, "the ticket was reusable"


def test_tickets_still_work_without_redis(monkeypatch):
    """The laptop path is one process and must not need Redis to authenticate."""
    from src.runtime import redis_client
    from auth import ws_tickets

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset()
    ws_tickets.clear()

    ticket = ws_tickets.issue("local-user")
    assert ws_tickets.redeem(ticket) == "local-user"
    assert ws_tickets.redeem(ticket) is None
    redis_client.reset()


def test_the_single_worker_warning_stands_down_when_tickets_are_shared(monkeypatch):
    """
    assert_single_worker exists to make multi-worker failure loud. Once tickets
    are shared it is no longer a failure, and a warning that fires when nothing
    is wrong is one people learn to ignore.
    """
    _needs_redis()
    from auth import ws_tickets

    _as_new_process(monkeypatch)
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    ws_tickets.assert_single_worker()   # must not raise, and must not object


# --- the event bus ----------------------------------------------------------

def test_a_worker_publish_reaches_a_separate_subscriber(monkeypatch):
    """
    THE gap this closes, and it was silent.

    Splitting into ROLE=api and ROLE=worker put the broadcaster and the sockets
    in different processes:

        worker  runs database_polling_loop -> manager.broadcast(...)
        api     accepts /ws               -> holds active_connections

    ConnectionManager is per-process, so the worker broadcast to a registry
    that is always empty while the API replicas held every socket and heard
    nothing. The live dashboard goes SILENT -- not broken-looking, just
    permanently stale -- in exactly the topology the k8s manifests describe.
    """
    _needs_redis()

    import asyncio

    from src.runtime import bus, redis_client

    monkeypatch.setenv("REDIS_URL", REDIS_URL)
    redis_client.reset()

    received = []

    async def scenario():
        async def handler(payload):
            received.append(payload)

        task = asyncio.create_task(bus.subscribe(handler))
        await asyncio.sleep(1.5)                    # let it subscribe
        published = bus.publish({"status": "operational", "total_events": 7})
        await asyncio.sleep(1.5)
        task.cancel()
        return published

    published = asyncio.run(scenario())

    assert published is True
    assert received and received[0]["total_events"] == 7, (
        "a worker-published event never reached a subscriber; API replicas "
        "would show a permanently stale dashboard"
    )
    redis_client.reset()


def test_publish_reports_failure_so_the_caller_can_broadcast_locally(monkeypatch):
    """
    The return value is the point. A silent False that the caller ignored would
    turn "no Redis" into "no live updates" for a single process -- which is the
    laptop, and which worked fine before any of this existed.
    """
    from src.runtime import bus, redis_client

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset()

    assert bus.publish({"anything": True}) is False
    redis_client.reset()


def test_the_poller_broadcasts_locally_only_when_the_bus_is_absent():
    """
    Doing both would deliver every event twice to a combined process, and
    doing neither is the silent-dashboard bug.
    """
    import ast

    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    loop = next(
        n for n in ast.walk(ast.parse(source))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "database_polling_loop"
    )
    body = ast.get_source_segment(source, loop) or ""

    assert "bus.publish" in body, "the poller does not publish to the bus"
    assert "if not bus.publish" in body, (
        "the poller either always broadcasts locally (duplicate delivery) or "
        "never does (silent for a single process)"
    )


# --- broadcast de-duplication -----------------------------------------------

def test_two_replicas_do_not_both_broadcast_one_event(monkeypatch):
    """
    Each replica kept its own seen-set, so whether a user saw an event twice
    depended on which replica they had connected to -- a bug that cannot be
    reproduced on request.
    """
    _needs_redis()
    from src.runtime import dedup

    event_id = f"ev-{uuid.uuid4().hex[:10]}"

    _as_new_process(monkeypatch)
    assert dedup.mark_if_new(event_id) is True
    dedup.clear()

    _as_new_process(monkeypatch)
    assert dedup.mark_if_new(event_id) is False, (
        "a second replica would broadcast the same event again"
    )


def test_marking_is_atomic_not_check_then_add():
    """
    A `seen()` / `add()` pair is a race: both replicas check, both find it
    absent, both broadcast. The API is deliberately one call.
    """
    from src.runtime import dedup

    assert hasattr(dedup, "mark_if_new")
    assert not hasattr(dedup, "add"), (
        "a separate add() invites the check-then-act race this replaces"
    )


def test_an_event_with_no_id_is_never_dropped():
    """
    It cannot be deduplicated, and silently discarding it would lose the event.
    Duplicates are cosmetic; losing intelligence is not.
    """
    from src.runtime import dedup

    assert dedup.mark_if_new(None) is True
    assert dedup.mark_if_new("") is True


def test_the_local_fallback_is_bounded(monkeypatch):
    """
    REGRESSION. The set it replaces had no bound and was never pruned, so a
    long-running process accumulated every event id it had ever seen.
    """
    from src.runtime import redis_client, dedup

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset()
    dedup.clear()

    monkeypatch.setattr(dedup, "LOCAL_MAX", 100)
    for i in range(500):
        dedup.mark_if_new(f"e{i}")

    assert dedup.local_size() <= 100, (
        f"the in-process set grew to {dedup.local_size()} with a cap of 100"
    )
    # Oldest evicted first, so a recent id is still remembered.
    assert dedup.mark_if_new("e499") is False
    dedup.clear()
    redis_client.reset()


# --- the live dashboard state -----------------------------------------------

def test_an_api_replica_sees_what_the_worker_wrote(monkeypatch):
    """
    THE failure this prevents, and it is a silent one.

    Only the worker runs the agent loop and the poller, so only the worker
    writes. With a module-level dict, every API replica serves its own
    untouched copy -- an empty feed and an "initializing" status forever, on
    two pods out of three, while the worker collects into a dict nobody can
    read. Nothing crashes; the dashboard is just permanently empty.
    """
    _needs_redis()
    from src.runtime import shared_state, redis_client

    _as_new_process(monkeypatch)
    redis_client.get_client().delete(shared_state.STATE_KEY)
    shared_state.reset()
    shared_state.update({
        "status": "operational",
        "run_count": 7,
        "final_ranked_feed": [{"event_id": "e1", "summary": "flood"}],
    })

    _as_new_process(monkeypatch)      # a different replica
    shared_state.reset()              # with its own empty local view
    snap = shared_state.snapshot()

    assert snap["status"] == "operational"
    assert snap["run_count"] == 7
    assert len(snap["final_ranked_feed"]) == 1

    redis_client.get_client().delete(shared_state.STATE_KEY)


def test_a_caller_mutating_the_snapshot_cannot_corrupt_the_store(monkeypatch):
    """
    main.py mutates what it reads. Handing out the cached object would let one
    request's edits leak into what every later request sees -- and with a
    one-second read cache, leak for a second across every route.
    """
    _needs_redis()
    from src.runtime import shared_state, redis_client

    _as_new_process(monkeypatch)
    redis_client.get_client().delete(shared_state.STATE_KEY)
    shared_state.reset()
    shared_state.update({"final_ranked_feed": [{"event_id": "real"}]})

    snap = shared_state.snapshot()
    snap["final_ranked_feed"].append({"event_id": "BOGUS"})
    snap["status"] = "tampered"

    fresh = shared_state.snapshot()
    assert len(fresh["final_ranked_feed"]) == 1
    assert fresh.get("status") != "tampered"

    redis_client.get_client().delete(shared_state.STATE_KEY)


def test_a_starting_replica_does_not_blank_a_running_workers_state(monkeypatch):
    """
    install_defaults seeds only the LOCAL view. If it wrote to Redis, every API
    pod starting during a deploy would overwrite the worker's live state with
    its own blank initial values -- blanking the dashboard on every rollout.
    """
    _needs_redis()
    from src.runtime import shared_state, redis_client

    _as_new_process(monkeypatch)
    shared_state.reset()
    shared_state.update({"status": "operational", "run_count": 42})

    _as_new_process(monkeypatch)      # a replica booting up
    shared_state.install_defaults({"status": "initializing", "run_count": 0})

    assert shared_state.snapshot()["run_count"] == 42, (
        "a starting replica overwrote the worker's state with its defaults"
    )
    redis_client.get_client().delete(shared_state.STATE_KEY)


def test_reads_fail_open_and_writes_never_raise(monkeypatch):
    """
    Opposite choice to the pacing gate, on purpose. A stale dashboard is
    cosmetic; refusing to serve one is not. The pacing gate fails CLOSED
    because its downside is a banned account.
    """
    from src.runtime import shared_state, redis_client

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6399/0")  # nothing there
    redis_client.reset()
    shared_state.reset()

    snap = shared_state.snapshot()          # must not raise
    assert isinstance(snap, dict)
    shared_state.update({"status": "x"})    # must not raise
    redis_client.reset()


def test_state_still_works_without_redis(monkeypatch):
    from src.runtime import shared_state, redis_client

    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset()
    shared_state.reset()

    shared_state.update({"status": "local-only", "run_count": 3})
    assert shared_state.get("status") == "local-only"
    assert shared_state.snapshot()["run_count"] == 3
    redis_client.reset()


def test_main_no_longer_holds_the_state_dict():
    """
    Asserted with AST for the same reason as the seen-set below: the comment
    explaining the change necessarily names the old binding.
    """
    import ast

    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            assert not (isinstance(target, ast.Name)
                        and target.id == "current_state"), (
                "main.py still binds a module-level current_state; API "
                "replicas would each serve their own copy"
            )


def test_main_no_longer_keeps_an_unbounded_set():
    """
    Asserted with AST, not a string search.

    A substring check matched the COMMENT that explains what was removed --
    quoting the old code in the explanation made the test fail while the code
    was correct. That is this repo's recurring test-writing bug (a test
    matching its own prose), and the fix is the same one used elsewhere here:
    ask the syntax tree, which sees bindings and not English.
    """
    import ast

    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in tree.body:            # module level only
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            assert not (isinstance(target, ast.Name)
                        and target.id == "seen_event_ids"), (
                "main.py still binds a module-level seen_event_ids; it is "
                "per-process and was never pruned"
            )

    assert "mark_if_new" in source
