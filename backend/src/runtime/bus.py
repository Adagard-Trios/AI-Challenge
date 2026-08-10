"""
src/runtime/bus.py
Getting a worker-produced event to a client attached to a different process.

THE GAP THIS CLOSES
-------------------
Splitting the process into ROLE=api and ROLE=worker put the broadcaster and the
sockets in different places:

    worker  runs database_polling_loop, calls manager.broadcast(...)
    api     accepts /ws, holds active_connections

ConnectionManager is per-process, so the worker broadcasts to a registry that
is always empty and the API replicas hold every socket and never hear anything.
The live dashboard goes SILENT -- not broken-looking, just permanently stale --
in exactly the topology the Kubernetes manifests describe.

Sticky sessions do not fix this and are worth ruling out explicitly: they pin a
CLIENT to a replica, but the event originates in the worker, which holds no
sockets at all. No amount of affinity routes a worker event to api-2.

So the worker PUBLISHES and every API replica SUBSCRIBES and re-broadcasts to
its own sockets. ConnectionManager is unchanged -- heartbeats, timeouts and
dead-connection reaping all keep working; it simply gains a second caller.

WITHOUT REDIS
-------------
Publishing falls back to nothing and the caller broadcasts locally, which is
correct for a single process that both polls and serves. That is what a laptop
runs, and it is why this is a no-op there rather than a new dependency.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("Roger.runtime.bus")

CHANNEL = "roger:events"


_WARNED_NO_REDIS = False


def _client():
    global _WARNED_NO_REDIS
    try:
        from src.runtime.redis_client import configured, get_client

        return get_client() if configured() else None
    except Exception:  # noqa: BLE001
        # Falling back to per-process is correct; doing it silently is
        # not. Without Redis there is no cross-replica broadcast, so
        # a WebSocket client only sees events from the replica it is attached to -- and the only
        # symptom is behaviour that reads as a different bug entirely.
        # Warned once, because this sits on a hot path.
        if not _WARNED_NO_REDIS:
            _WARNED_NO_REDIS = True
            logger.warning(
                "[bus] Redis unavailable; using per-process fallback. "
                "With more than one replica, a WebSocket client only sees events from the replica it is attached to.",
                exc_info=True,
            )
        return None


def enabled() -> bool:
    return _client() is not None


def publish(payload: Dict[str, Any]) -> bool:
    """
    Send state to every subscribed replica. Returns whether it went anywhere.

    False means the caller must broadcast locally instead -- which is exactly
    the single-process behaviour. A silent False that the caller ignored would
    turn "no Redis" into "no live updates", so the return value is the point.
    """
    client = _client()
    if client is None:
        return False
    try:
        client.publish(CHANNEL, json.dumps(payload, default=str))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[bus] publish failed (%s); the caller should "
                       "broadcast locally", exc)
        return False


async def subscribe(handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
    """
    Long-running subscriber. One per API replica, started at startup.

    Runs the blocking Redis listen loop in a thread so it cannot stall the
    event loop that is also serving requests -- redis-py's sync pubsub blocks,
    and blocking here would freeze every route on the pod.

    Reconnects rather than exiting. A subscriber that dies on the first network
    blip leaves that replica permanently silent while looking healthy, which is
    the same class of failure this module exists to fix.
    """
    loop = asyncio.get_running_loop()

    while True:
        client = _client()
        if client is None:
            # Nothing to subscribe to. Sleep rather than spin: this replica
            # simply has no shared bus.
            await asyncio.sleep(30)
            continue

        pubsub = None
        try:
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(CHANNEL)
            logger.info("[bus] subscribed to %s", CHANNEL)

            def _next():
                # Timeout so the loop can notice cancellation and reconnect
                # rather than blocking forever on a dead connection.
                return pubsub.get_message(timeout=5.0)

            while True:
                message = await loop.run_in_executor(None, _next)
                if not message:
                    continue
                try:
                    payload = json.loads(message.get("data") or "{}")
                except Exception:  # noqa: BLE001
                    continue
                if payload:
                    await handler(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("[bus] subscription dropped (%s); reconnecting", exc)
            await asyncio.sleep(5)
        finally:
            try:
                if pubsub is not None:
                    pubsub.close()
            except Exception:  # noqa: BLE001
                pass
