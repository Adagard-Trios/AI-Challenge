"""
main.py
Production-Ready Real-Time Intelligence Platform Backend
- Uses combinedAgentGraph for multi-agent orchestration
- Threading for concurrent graph execution and WebSocket server
- Database-driven feed updates with polling
- Duplicate prevention
- District-based feed categorization for map display

Updated: Resilient WebSocket handling for long scraping operations (60s+ cycles)
"""
from fastapi import Depends, FastAPI, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Set, Optional
import asyncio
import json
from datetime import datetime, timedelta, timezone
import sys
import os
import logging
import threading
from collections import OrderedDict
import time
import uuid  # CRITICAL: Was missing, needed for event_id generation


def utc_now() -> datetime:
    """Return current UTC time (Python 3.12+ compatible)."""
    return datetime.now(timezone.utc)


sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# NB: the graph is deliberately NOT imported here. Building it constructs every
# agent, ToolSet and Neo4j/ChromaDB manager -- tens of seconds and hundreds of
# MB -- which delayed uvicorn's bind long enough to fail Render's 5s health
# check. run_graph_loop imports it inside the worker thread instead, so the API
# is serving before any of that starts.
from src.states.combinedAgentState import CombinedAgentState
from src.storage.storage_manager import StorageManager
from src import model_gateway, model_metadata
from src.intelligence import feed_relevance

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Roger_api")


# ============================================
# AUTO-TRAINING: Check and train models if missing
# ============================================

def check_and_train_models():
    """
    Check if ML models are trained. If not, trigger training in background.
    Called on startup to ensure models are available.
    """
    from pathlib import Path
    import subprocess

    PROJECT_ROOT = Path(__file__).parent.parent

    # Define model checks: (name, model_path, train_command)
    model_checks = [
        {
            "name": "Anomaly Detection",
            "check_paths": [
                PROJECT_ROOT / "models" / "anomaly-detection" / "artifacts" / "models",
            ],
            "check_files": ["*.joblib", "*.pkl"],
            "train_cmd": [
                sys.executable,
                str(PROJECT_ROOT / "models" / "anomaly-detection" / "main.py")
            ]
        },
        {
            "name": "Weather Prediction",
            "check_paths": [
                PROJECT_ROOT / "models" / "weather-prediction" / "artifacts" / "models",
            ],
            "check_files": ["*.h5", "*.keras"],
            "train_cmd": [
                sys.executable,
                str(PROJECT_ROOT / "models" / "weather-prediction" / "main.py"),
                "--mode", "full"
            ]
        },
        {
            "name": "Currency Prediction",
            "check_paths": [
                PROJECT_ROOT / "models" / "currency-volatility-prediction"
                / "artifacts" / "models",
            ],
            "check_files": ["*.h5", "*.keras"],
            "train_cmd": [
                sys.executable,
                str(PROJECT_ROOT / "models" / "currency-volatility-prediction"
                    / "main.py"),
                "--mode", "full"
            ]
        },
        {
            "name": "Stock Prediction",
            "check_paths": [
                PROJECT_ROOT / "models" / "stock-price-prediction"
                / "Artifacts",
            ],
            "check_files": ["*.pkl", "*.h5", "*.keras"],
            "train_cmd": [
                sys.executable,
                str(PROJECT_ROOT / "models" / "stock-price-prediction"
                    / "main.py")
            ]
        },
    ]

    def has_trained_model(check_paths, check_files):
        """Check if any trained model files exist."""
        for path in check_paths:
            if path.exists():
                for pattern in check_files:
                    if list(path.glob(pattern)):
                        return True
                    # Also check subdirectories
                    if list(path.glob(f"**/{pattern}")):
                        return True
        return False

    def train_in_background(name, cmd):
        """Run training in a background thread."""
        def _train():
            logger.info(f"[AUTO-TRAIN] Starting {name} training...")
            try:
                result = subprocess.run(
                    cmd,
                    cwd=str(Path(__file__).parent),
                    capture_output=True,
                    text=True,
                    timeout=1800  # 30 min timeout
                )
                if result.returncode == 0:
                    logger.info(f"[AUTO-TRAIN] ✓ {name} training complete!")
                else:
                    logger.warning(f"[AUTO-TRAIN] ⚠ {name} training failed: {result.stderr[:500]}")
            except subprocess.TimeoutExpired:
                logger.error(f"[AUTO-TRAIN] ✗ {name} training timed out (30 min)")
            except Exception as e:
                logger.error(f"[AUTO-TRAIN] ✗ {name} training error: {e}")

        thread = threading.Thread(target=_train, daemon=True, name=f"train_{name}")
        thread.start()
        return thread

    # Check each model
    training_threads = []
    for model in model_checks:
        if has_trained_model(model["check_paths"], model["check_files"]):
            logger.info(f"[MODEL CHECK] ✓ {model['name']} - Model found")
        else:
            logger.warning(f"[MODEL CHECK] ⚠ {model['name']} - No model found, starting training...")
            thread = train_in_background(model["name"], model["train_cmd"])
            training_threads.append((model["name"], thread))

    if training_threads:
        logger.info(f"[AUTO-TRAIN] Started {len(training_threads)} background training jobs")
    else:
        logger.info("[MODEL CHECK] All models found - no training needed")

    return training_threads


# Run model check on module load (startup)
logger.info("=" * 60)
logger.info("[STARTUP] Checking ML models...")
logger.info("=" * 60)

# On memory-capped PaaS hosts (Render, HF Spaces) the auto-trainer forks ML
# training subprocesses on every cold start, which OOMs the instance before it
# can bind $PORT. Set DISABLE_AUTO_TRAIN=1 there and ship pre-trained artifacts.
if os.getenv("DISABLE_AUTO_TRAIN", "").strip().lower() in ("1", "true", "yes"):
    logger.info("[STARTUP] Auto-training disabled (DISABLE_AUTO_TRAIN set)")
    _training_threads = []
else:
    _training_threads = check_and_train_models()

app = FastAPI(title="Roger Intelligence Platform API")

# Comma-separated allowlist, e.g. "https://your-app.vercel.app". Defaults to "*".
# Note: the CORS spec forbids credentials with a wildcard origin, and browsers
# reject that combination — so credentials are only enabled for a real allowlist.
_cors_origins = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
] or ["*"]
_cors_wildcard = _cors_origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _cors_wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(
    f"[STARTUP] CORS origins: {_cors_origins} "
    f"(credentials={'off' if _cors_wildcard else 'on'})"
)

# ============================================
# CONFIGURATION PREFLIGHT
# ============================================
# Runs before auth so that a missing DATABASE_URL is reported as a named
# problem with a stated consequence, rather than as a silent fallback to a
# SQLite file that is wiped on the next restart. Reporting only -- enforcement
# stays in auth/config.py, which fails closed where it must.
try:
    from src import preflight as _preflight

    _PREFLIGHT = _preflight.report()
except Exception:  # noqa: BLE001
    logger.exception("[STARTUP] preflight failed to run")
    _preflight = None
    _PREFLIGHT = None

# ============================================
# AUTH
# ============================================
# Registered as an APIRouter. The 39 pre-existing routes below are deliberately
# left as plain @app decorators -- converting them would be a large, risky diff
# with no user-visible benefit, on a file that has already hidden three
# duplicate-registration bugs.
#
# AUTH_ENFORCED=0 (the default) means require_user resolves a user when a token
# is present and returns None otherwise, so every existing route keeps working
# while the frontend migrates. Enforcement is a one-env-var cutover.
try:
    from auth import bootstrap as _auth_bootstrap
    from auth import routes as _auth_routes
    from auth import ws_tickets as _ws_tickets
    from auth.config import settings as _auth_settings
    from auth.db import get_db
    from auth.dependencies import require_user

    _AUTH_READY = _auth_bootstrap.init()
    app.include_router(_auth_routes.router)

    # Exposure profiles are per-user and live in the same database, so they
    # only mount when the auth layer came up. Without them the feed is simply
    # unranked -- relevance is null and the order is unchanged.
    from src.intelligence import exposure_routes as _exposure_routes

    app.include_router(_exposure_routes.router)

    # Social accounts connected from the dashboard itself, for the case where
    # this server IS the user's machine. Shares the connector's vault and
    # session store, so the CLI and the web UI see the same accounts rather
    # than each keeping a private copy -- one store, two front doors.
    from src.social import routes as _social_routes

    app.include_router(_social_routes.router)

    # Point the scrapers at those accounts.
    #
    # Without this the feature is complete right up to the part that matters:
    # you can sign in, see "Connected" with a handle and an expiry, and the five
    # agents still scrape nothing -- because every scraper calls
    # get_credential(), whose default hands out nothing. No error, just a social
    # feed that is permanently empty.
    from src.social import credential_bridge as _credential_bridge

    _credential_bridge.install()
except Exception:  # noqa: BLE001
    # Never let an auth problem take down a service that ran fine without it.
    # bootstrap.init() itself re-raises when AUTH_ENFORCED=1, which is the case
    # where failing loudly is correct.
    logger.exception("[STARTUP] auth layer unavailable; continuing without it")
    _AUTH_READY = False
    _ws_tickets = None
    _auth_settings = None

    # Routes below declare Depends(require_user). If the auth package failed to
    # import we still need a callable with that name, or every route 500s at
    # definition time -- turning an auth problem into a total outage, which is
    # the opposite of degrading gracefully.
    def require_user():  # type: ignore[misc]
        return None

    # Same reasoning for the session dependency. Yielding None means
    # feed_relevance.load_exposure() returns no exposure, so the feed is served
    # unranked rather than 500ing.
    def get_db():  # type: ignore[misc]
        yield None

# Global state
current_state: Dict[str, Any] = {
    "final_ranked_feed": [],
    "risk_dashboard_snapshot": {
        "logistics_friction": 0.0,
        "compliance_volatility": 0.0,
        "market_instability": 0.0,
        "opportunity_index": 0.0,
        "avg_confidence": 0.0,
        "high_priority_count": 0,
        "total_events": 0,
        "last_updated": utc_now().isoformat()
    },
    "run_count": 0,
    "status": "initializing",
    "first_run_complete": False  # Track first graph execution
}

# Thread-safe communication
feed_update_queue = asyncio.Queue()
# Broadcast de-duplication.
#
# This was `seen_event_ids: Set[str] = set()` -- unbounded, per-process, and
# emptied on restart, so a long run leaked and a restart re-broadcast
# everything. src/runtime/dedup keeps it in Redis when configured (atomic,
# shared, self-expiring) and in a bounded LRU when not.
from src.runtime.dedup import mark_if_new  # noqa: E402

# Global event loop reference for cross-thread broadcasting
main_event_loop = None

# Storage manager
storage_manager = StorageManager()

# WebSocket settings - ULTRA-RESILIENT for long scraping operations
# Heavy graph cycles can take 2-3 minutes, so we need high tolerance
HEARTBEAT_INTERVAL = 60.0  # Send ping every 60s (increased from 45s)
HEARTBEAT_TIMEOUT = 45.0   # Wait 45s for pong (increased from 30s) 
HEARTBEAT_MISS_THRESHOLD = 5  # Allow 5 misses = ~5 minutes tolerance
SEND_TIMEOUT = 15.0  # Increased for slow networks/heavy load

class ConnectionManager:
    """Manages active WebSocket with heartbeat"""
    def __init__(self):
        self.active_connections: Dict[WebSocket, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            meta = {
                "heartbeat_task": asyncio.create_task(self._heartbeat_loop(websocket)),
                "last_pong": utc_now(),
                "misses": 0
            }
            self.active_connections[websocket] = meta
            logger.info(f"[WebSocket] Connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            meta = self.active_connections.pop(websocket, None)
        if meta:
            task = meta.get("heartbeat_task")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            try:
                await websocket.close()
            except Exception:
                pass
            logger.info(f"[WebSocket] Disconnected. Total: {len(self.active_connections)}")

    async def _send_with_timeout(self, websocket: WebSocket, message_json: str):
        try:
            await asyncio.wait_for(websocket.send_text(message_json), timeout=SEND_TIMEOUT)
            return True
        except Exception as e:
            logger.debug(f"[WebSocket] Send failed: {e}")
            return False

    async def _heartbeat_loop(self, websocket: WebSocket):
        """Per-connection heartbeat task"""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if websocket not in self.active_connections:
                    break

                ping_payload = json.dumps({"type": "ping"})
                ok = await self._send_with_timeout(websocket, ping_payload)
                if not ok:
                    async with self._lock:
                        meta = self.active_connections.get(websocket)
                        if meta is not None:
                            meta['misses'] += 1
                else:
                    waited = 0.0
                    sleep_step = 0.5
                    pong_received = False
                    while waited < HEARTBEAT_TIMEOUT:
                        await asyncio.sleep(sleep_step)
                        waited += sleep_step
                        async with self._lock:
                            meta = self.active_connections.get(websocket)
                            if meta is None:
                                return
                            last_pong = meta.get("last_pong")
                            if last_pong and (utc_now() - last_pong).total_seconds() < (HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT):
                                pong_received = True
                                meta['misses'] = 0
                                break
                    if not pong_received:
                        async with self._lock:
                            meta = self.active_connections.get(websocket)
                            if meta is not None:
                                meta['misses'] += 1

                async with self._lock:
                    meta = self.active_connections.get(websocket)
                    if meta is None:
                        return
                    if meta.get('misses', 0) >= HEARTBEAT_MISS_THRESHOLD:
                        logger.warning("[WebSocket] Miss threshold exceeded, disconnecting")
                        try:
                            await websocket.close(code=1001)
                        except Exception:
                            pass
                        await self.disconnect(websocket)
                        return

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception(f"[WebSocket] Heartbeat error: {e}")
            try:
                await self.disconnect(websocket)
            except Exception:
                pass

    async def broadcast(self, message: dict):
        """Broadcast to all connections"""
        async with self._lock:
            conns = list(self.active_connections.keys())
        if not conns:
            return
        message_json = json.dumps(message, default=str)
        dead: List[WebSocket] = []
        for conn in conns:
            ok = await self._send_with_timeout(conn, message_json)
            if not ok:
                dead.append(conn)
        for conn in dead:
            logger.info("[WebSocket] Removing dead connection")
            await self.disconnect(conn)

manager = ConnectionManager()


def categorize_feed_by_district(feed: Dict[str, Any]) -> str:
    """
    Categorize feed by Sri Lankan district based on summary text.
    Returns district name or "National" if not district-specific.
    NOTE: This returns the FIRST match. Use get_all_matching_districts() for multi-district feeds.
    """
    districts = get_all_matching_districts(feed)
    return districts[0] if districts else "National"


def get_all_matching_districts(feed: Dict[str, Any]) -> List[str]:
    """
    Get ALL districts mentioned in a feed (direct or via province).
    
    Supports:
    - Direct district names (Colombo, Kandy, etc.)
    - Province names that map to multiple districts
    - Commonly referenced regions
    
    Returns list of all matching district names.
    """
    summary = feed.get("summary", "").lower()

    # Sri Lankan districts
    districts = [
        "Colombo", "Gampaha", "Kalutara", "Kandy", "Matale", "Nuwara Eliya",
        "Galle", "Matara", "Hambantota", "Jaffna", "Kilinochchi", "Mannar",
        "Vavuniya", "Mullaitivu", "Batticaloa", "Ampara", "Trincomalee",
        "Kurunegala", "Puttalam", "Anuradhapura", "Polonnaruwa", "Badulla",
        "Moneragala", "Ratnapura", "Kegalle"
    ]

    # Province to districts mapping
    province_mapping = {
        "western province": ["Colombo", "Gampaha", "Kalutara"],
        "western": ["Colombo", "Gampaha", "Kalutara"],
        "central province": ["Kandy", "Matale", "Nuwara Eliya"],
        "central": ["Kandy", "Matale", "Nuwara Eliya"],
        "southern province": ["Galle", "Matara", "Hambantota"],
        "southern provinces": ["Galle", "Matara", "Hambantota"],
        "southern": ["Galle", "Matara", "Hambantota"],
        "south": ["Galle", "Matara", "Hambantota"],
        "northern province": ["Jaffna", "Kilinochchi", "Mannar", "Vavuniya", "Mullaitivu"],
        "northern": ["Jaffna", "Kilinochchi", "Mannar", "Vavuniya", "Mullaitivu"],
        "north": ["Jaffna", "Kilinochchi", "Mannar", "Vavuniya", "Mullaitivu"],
        "eastern province": ["Batticaloa", "Ampara", "Trincomalee"],
        "eastern": ["Batticaloa", "Ampara", "Trincomalee"],
        "east": ["Batticaloa", "Ampara", "Trincomalee"],
        "north western province": ["Kurunegala", "Puttalam"],
        "north western": ["Kurunegala", "Puttalam"],
        "north central province": ["Anuradhapura", "Polonnaruwa"],
        "north central": ["Anuradhapura", "Polonnaruwa"],
        "uva province": ["Badulla", "Moneragala"],
        "uva": ["Badulla", "Moneragala"],
        "sabaragamuwa province": ["Ratnapura", "Kegalle"],
        "sabaragamuwa": ["Ratnapura", "Kegalle"],
    }

    matched_districts = set()

    # Check for province mentions first
    for province, province_districts in province_mapping.items():
        if province in summary:
            matched_districts.update(province_districts)

    # Check for direct district mentions
    for district in districts:
        if district.lower() in summary:
            matched_districts.add(district)

    return list(matched_districts)


def run_graph_loop():
    """
    Graph execution in separate thread.
    Runs the combinedAgentGraph every 60 seconds (non-blocking pattern).
    
    UPDATED: Graph now runs single cycles and this loop handles the 60s interval
    externally, making the pattern non-blocking and interruptible.
    """
    # Seconds between cycles. Configurable because 60 is not a safe default
    # everywhere and there was no way to change it without editing this file.
    #
    # A cycle spends the Groq allowance five times over -- one LLM summary per
    # domain plus batched filter calls -- against a free tier of 8,000 tokens
    # per MINUTE, which this project already hits (HTTP 413). Adding replicas
    # does not help: they add zero tokens. Lengthening this does.
    #
    # It is also the wrong knob to reach for if the feed looks thin; that is
    # what the collection sources are for.
    try:
        REFRESH_INTERVAL_SECONDS = float(
            os.getenv("AGENT_LOOP_INTERVAL_SECONDS", "60")
        )
    except ValueError:
        logger.warning("[GRAPH] AGENT_LOOP_INTERVAL_SECONDS is not a number; "
                       "using 60")
        REFRESH_INTERVAL_SECONDS = 60.0
    if REFRESH_INTERVAL_SECONDS < 10:
        logger.warning("[GRAPH] AGENT_LOOP_INTERVAL_SECONDS=%.0f is below the "
                       "10s floor; using 10", REFRESH_INTERVAL_SECONDS)
        REFRESH_INTERVAL_SECONDS = 10.0

    shutdown_event = threading.Event()

    # Hold off the first cycle so the platform health check can pass first.
    #
    # A cycle fans out to five scraping agents and launches Playwright Chromium.
    # On a small shared-CPU instance that saturates the box, and /api/status stops
    # answering inside the health-check timeout -- the instance is then killed and
    # restarted, which starts another cycle, forever.
    #
    # 0 disables the delay (the historical behaviour).
    try:
        start_delay = float(os.getenv("AGENT_LOOP_START_DELAY", "45"))
    except ValueError:
        start_delay = 45.0

    logger.info("="*80)
    logger.info("[GRAPH THREAD] Starting Roger combinedAgentGraph loop (60s interval)")
    if start_delay > 0:
        logger.info(f"[GRAPH THREAD] Waiting {start_delay:.0f}s before first cycle "
                    f"(AGENT_LOOP_START_DELAY) so health checks can pass")
    logger.info("="*80)

    if start_delay > 0 and shutdown_event.wait(timeout=start_delay):
        return

    # Imported here, not at module scope: this is what actually builds the graph
    # (combinedAgentGraph exposes it through a lazy module __getattr__), and it
    # must not happen on the import path that uvicorn's startup blocks on.
    logger.info("[GRAPH THREAD] Building agent graph...")
    from src.graphs.combinedAgentGraph import graph

    logger.info("[GRAPH THREAD] Agent graph ready")

    cycle_count = 0
    
    while not shutdown_event.is_set():
        cycle_count += 1
        cycle_start = time.time()
        
        logger.info(f"[GRAPH THREAD] Starting cycle #{cycle_count}")
        
        initial_state = CombinedAgentState(
            domain_insights=[],
            final_ranked_feed=[],
            run_count=cycle_count,
            max_runs=1,  # Single cycle mode
            route=None
        )

        try:
            # Run a single graph cycle (non-blocking since router now returns END)
            config = {"recursion_limit": 100}
            for event in graph.stream(initial_state, config=config):
                logger.info(f"[GRAPH] Event nodes: {list(event.keys())}")

                for node_name, node_output in event.items():
                    # The risk indices, which used to be computed and thrown
                    # away.
                    #
                    # DataRefresherAgent builds a full snapshot every cycle --
                    # logistics_friction, compliance_volatility,
                    # market_instability, opportunity_index and the driver
                    # events behind each -- and returns it as
                    # risk_dashboard_snapshot. Nothing here ever read it, so
                    # the only two mentions of that key in this file were the
                    # zeroed literal it is initialised with and the line
                    # /api/dashboard serves it from.
                    #
                    # The dashboard therefore served zeros for the entire
                    # lifetime of the process, on every deployment, while a
                    # perfectly good snapshot was discarded sixty seconds
                    # apart. Merged rather than replaced so a node that
                    # reports only part of the snapshot cannot blank the rest.
                    snapshot = None
                    if hasattr(node_output, "risk_dashboard_snapshot"):
                        snapshot = node_output.risk_dashboard_snapshot
                    elif isinstance(node_output, dict):
                        snapshot = node_output.get("risk_dashboard_snapshot")
                    if snapshot:
                        current_state["risk_dashboard_snapshot"] = {
                            **current_state.get("risk_dashboard_snapshot", {}),
                            **snapshot,
                        }
                        logger.info(
                            "[GRAPH] %s updated the risk snapshot "
                            "(%d events, %d high priority)",
                            node_name,
                            snapshot.get("total_events", 0),
                            snapshot.get("high_priority_count", 0),
                        )

                    # Extract feed data
                    if hasattr(node_output, 'final_ranked_feed'):
                        feeds = node_output.final_ranked_feed
                    elif isinstance(node_output, dict):
                        feeds = node_output.get('final_ranked_feed', [])
                    else:
                        continue

                    if feeds:
                        logger.info(f"[GRAPH] {node_name} produced {len(feeds)} feeds")

                        # FIELD_NORMALIZATION: Transform graph format to frontend format
                        for feed_item in feeds:
                            if isinstance(feed_item, dict):
                                event_data = feed_item
                            else:
                                event_data = feed_item.__dict__ if hasattr(feed_item, '__dict__') else {}

                            # Normalize field names: graph uses content_summary/target_agent, frontend expects summary/domain
                            event_id = event_data.get("event_id", str(uuid.uuid4()))
                            summary = event_data.get("content_summary") or event_data.get("summary", "")
                            domain = event_data.get("target_agent") or event_data.get("domain", "unknown")
                            severity = event_data.get("severity", "medium")
                            impact_type = event_data.get("impact_type", "risk")
                            confidence = event_data.get("confidence_score", event_data.get("confidence", 0.5))
                            timestamp = event_data.get("timestamp", utc_now().isoformat())

                            # Check for duplicates
                            is_dup, _, _ = storage_manager.is_duplicate(summary)

                            if not is_dup:
                                try:
                                    storage_manager.store_event(
                                        event_id=event_id,
                                        summary=summary,
                                        domain=domain,
                                        severity=severity,
                                        impact_type=impact_type,
                                        confidence_score=confidence,
                                        # Without this the entity store never
                                        # learns about events stored on this
                                        # path, so relevance scoring has nothing
                                        # to join a user's exposure against and
                                        # falls back to keyword matching alone.
                                        entities=event_data.get("entities"),
                                    )
                                    logger.info(f"[GRAPH] Stored new feed: {summary[:60]}...")
                                except Exception as storage_error:
                                    logger.warning(f"[GRAPH] Storage error (continuing): {storage_error}")

                            # DIRECT_BROADCAST_FIX: Set first_run_complete and broadcast
                            if not current_state.get('first_run_complete'):
                                current_state['first_run_complete'] = True
                                current_state['status'] = 'operational'
                                logger.info("[GRAPH] FIRST RUN COMPLETE - Broadcasting to frontend!")

                                # Trigger broadcast from sync thread to async loop
                                if main_event_loop:
                                    asyncio.run_coroutine_threadsafe(
                                        manager.broadcast(current_state),
                                        main_event_loop
                                    )

        except RuntimeError as e:
            if "cannot schedule new futures after interpreter shutdown" in str(e):
                logger.warning("[GRAPH THREAD] Interpreter shutting down, stopping graph loop gracefully")
                break  # Exit the loop cleanly
            else:
                logger.error(f"[GRAPH THREAD] RuntimeError in cycle #{cycle_count}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"[GRAPH THREAD] Error in cycle #{cycle_count}: {e}", exc_info=True)

        # Calculate time spent in this cycle
        cycle_duration = time.time() - cycle_start
        logger.info(f"[GRAPH THREAD] Cycle #{cycle_count} completed in {cycle_duration:.1f}s")
        
        # Wait for remaining time to complete 60s interval (interruptible)
        wait_time = max(0, REFRESH_INTERVAL_SECONDS - cycle_duration)
        if wait_time > 0:
            logger.info(f"[GRAPH THREAD] Waiting {wait_time:.1f}s before next cycle...")
            # Use Event.wait() for interruptible sleep instead of time.sleep()
            shutdown_event.wait(timeout=wait_time)
    
    logger.info("[GRAPH THREAD] Graph loop stopped")



async def database_polling_loop():
    """
    Polls database for new feeds and broadcasts via WebSocket.
    Runs concurrently with graph thread.
    """
    global current_state
    last_check = utc_now()

    logger.info("[DB_POLLER] Starting database polling loop")

    while True:
        try:
            await asyncio.sleep(2.0)  # Poll every 2 seconds

            # Get new feeds since last check.
            # Off the event loop: get_feeds_since() is a synchronous SQLite read,
            # and awaiting it inline stalls every other request -- including the
            # platform health check -- for its duration, every 2 seconds.
            _check_from = last_check
            new_feeds = await asyncio.get_running_loop().run_in_executor(
                None, storage_manager.get_feeds_since, _check_from
            )
            last_check = utc_now()

            if new_feeds:
                logger.info(f"[DB_POLLER] Found {len(new_feeds)} new feeds")

                # Filter duplicates (by event_id).
                #
                # mark_if_new is one atomic operation rather than a
                # check-then-add pair: with replicas, two pollers both find the
                # id absent and both broadcast, so whether a user sees an event
                # twice depends on which replica they connected to.
                unique_feeds = []
                for feed in new_feeds:
                    event_id = feed.get("event_id")
                    if event_id and mark_if_new(event_id):
                        # Add district categorization for map
                        feed["district"] = categorize_feed_by_district(feed)
                        unique_feeds.append(feed)

                if unique_feeds:
                    # Update current state
                    current_state['final_ranked_feed'] = unique_feeds + current_state.get('final_ranked_feed', [])
                    current_state['final_ranked_feed'] = current_state['final_ranked_feed'][:100]  # Keep last 100
                    current_state['status'] = 'operational'
                    current_state['last_update'] = utc_now().isoformat()

                    # Mark first run as complete (frontend loading screen can now hide)
                    if not current_state.get('first_run_complete'):
                        current_state['first_run_complete'] = True
                        logger.info("[DB_POLLER] First graph run complete! Frontend loading screen can now hide.")

                    # Broadcast to WebSocket clients
                    await manager.broadcast(current_state)
                    logger.info(f"[DB_POLLER] Broadcasted {len(unique_feeds)} unique feeds")

        except Exception as e:
            logger.error(f"[DB_POLLER] Error: {e}")



@app.on_event("startup")
async def startup_event():
    global main_event_loop
    main_event_loop = asyncio.get_event_loop()

    logger.info("[API] Starting Roger API...")

    # Refuse to come up misconfigured when this instance is internet-facing.
    #
    # These checks used to live only in scripts/serve_public.py, which is a CLI
    # and is NOT the container entrypoint -- the image runs start_backend.sh.
    # So every check was bypassed exactly when it mattered most, which is the
    # moment the API is containerised and put behind a public URL.
    #
    # No-op unless PUBLIC_HOSTING=1. Raising here means a misconfigured public
    # deployment crash-loops with the reason in its logs, which is the right
    # outcome -- it should not serve.
    from src.config.public_guard import enforce_at_startup

    enforce_at_startup()

    # Which half of the system is this process?
    #
    # "worker" collects: it runs the agent loop and the storage poller. "api"
    # only serves HTTP. Unset means "both", which is exactly today's behaviour
    # and what a single local process wants.
    #
    # This exists so the same image can be deployed twice -- N api replicas and
    # exactly ONE worker. The collection side is single-writer by design: two
    # workers means two agent cycles spending the same Groq allowance (already
    # at its 8,000 tokens/minute ceiling at one replica) and two schedules
    # hitting one personal social account.
    role = (os.getenv("ROLE") or "").strip().lower()
    if role not in ("", "api", "worker"):
        logger.warning("[API] ROLE=%r is not one of api|worker; treating as "
                       "unset (this process will do both)", role)
        role = ""
    collects = role in ("", "worker")

    # Start graph execution in separate thread.
    #
    # DISABLE_AGENT_LOOP=1 serves the API without the scraping agents. Useful on
    # memory-capped hosts: a cycle launches Playwright Chromium (100-300 MB) on
    # top of the ~210 MB base, which is what tips a 512 MB instance over.
    if os.getenv("DISABLE_AGENT_LOOP", "").lower() in ("1", "true", "yes"):
        logger.warning("[API] Agent loop disabled (DISABLE_AGENT_LOOP set) — "
                       "serving cached/stored feeds only, no live collection")
    elif not collects:
        logger.info("[API] ROLE=api — no agent loop here; the worker collects")
    else:
        graph_thread = threading.Thread(target=run_graph_loop, daemon=True)
        graph_thread.start()
        logger.info("[API] Graph thread started")

    # Start database polling loop.
    #
    # Gated on ROLE rather than DISABLE_AGENT_LOOP: they are different
    # questions. An api replica with the agent loop off still must not poll and
    # broadcast, or every replica broadcasts the same events to its own
    # WebSocket clients and each keeps a private seen-set.
    if collects:
        asyncio.create_task(database_polling_loop())
        logger.info("[API] Database polling started")
    else:
        logger.info("[API] ROLE=api — not polling storage; the worker does")


@app.get("/")
def read_root():
    return {
        "service": "Roger Intelligence Platform",
        "status": current_state.get("status"),
        "version": "2.0.0 (Database-Driven)"
    }


@app.get("/healthz")
async def healthz():
    """
    Liveness. Deliberately async, and deliberately does nothing.

    THIS MUST NOT BECOME A SYNC DEF, and orchestrators must not probe
    /api/status instead.

    Most routes in this file are sync `def`, which FastAPI runs in AnyIO's
    threadpool -- 40 threads by default. rag_chat blocks on Groq for seconds
    and predict_anomaly blocks on joblib, so a modest burst of either
    saturates the pool and every remaining sync route QUEUES BEHIND IT,
    including a health check.

    Point a Kubernetes livenessProbe at a queued endpoint and the failure is
    self-amplifying: load -> probe times out -> kubelet kills a perfectly
    healthy pod -> its traffic shifts to the survivors -> they saturate too.
    Scaling up then causes the outage it was meant to prevent, and it presents
    as "Kubernetes keeps restarting my pods under load".

    Being async means this runs on the event loop and cannot queue behind
    threadpool work, whatever the API is doing.
    """
    return {"ok": True}


@app.get("/readyz")
async def readyz(response: Response):
    """
    Readiness: should this replica receive traffic right now?

    Distinct from liveness on purpose. A pod whose database is briefly
    unreachable should be taken OUT OF THE LOAD BALANCER, not killed and
    restarted -- restarting it does not fix the database and throws away a warm
    process.

    Returns 503 rather than raising so it stays cheap under failure.
    """
    checks: Dict[str, Any] = {}
    ok = True

    try:
        from auth.db import ping as _db_ping

        checks["database"] = bool(_db_ping())
    except Exception as exc:  # noqa: BLE001
        # Booleans only. This endpoint is unauthenticated by necessity -- a
        # kubelet presents no credentials -- and a SQLAlchemy connection error
        # embeds the DSN, which carries the database password. The reason goes
        # to the log, where it is useful and not world-readable.
        logger.warning("[readyz] database check failed: %s", exc)
        checks["database"] = False
    ok = ok and checks.get("database", False)

    if not ok:
        response.status_code = 503
    return {"ready": ok, "checks": checks}


@app.get("/api/status")
def get_status():
    """
    Configuration report. NOT a probe -- see /healthz for why.

    Render's health check hits this, so it stays cheap and never raises. The
    `configuration` block exists because the deployed instance has no shell:
    when a feature is missing in production, this is the only place that says
    which variable is unset and what it broke. It reports whether a value is
    present, never the value itself.
    """
    body = {
        "status": current_state.get("status"),
        "run_count": current_state.get("run_count"),
        "last_update": current_state.get("last_update"),
        "active_connections": len(manager.active_connections),
        "total_events": len(current_state.get("final_ranked_feed", []))
    }

    if _preflight is not None:
        try:
            body["configuration"] = _preflight.run().as_dict()
        except Exception:  # noqa: BLE001
            logger.exception("[status] preflight unavailable")

    return body


@app.get("/api/dashboard")
def get_dashboard(_user=Depends(require_user)):
    return current_state.get("risk_dashboard_snapshot", {})


@app.get("/api/feed")
def get_feed(
    only_relevant: bool = False,
    _user=Depends(require_user),
    db=Depends(get_db),
):
    """
    Current feed from memory, ranked against the caller's exposure profile.

    A caller with no profile gets the feed exactly as before, in the same
    order, with relevance null on every event -- explicitly "not scored", never
    a score of zero.
    """
    events = list(current_state.get("final_ranked_feed", []))

    exposure = feed_relevance.load_exposure(db, _user)
    events = feed_relevance.annotate(events, exposure, only_relevant=only_relevant)

    return {
        "events": events,
        "total": len(events),
        "ranked_by_relevance": exposure is not None,
    }


@app.get("/api/stories")
def get_stories(limit: int = 20, _user=Depends(require_user)):
    """
    Ongoing stories -- events threaded together rather than deduplicated away.

    Empty when threading has no database to write to, which is honest: no
    stories exist in that case, as opposed to none having happened.
    """
    from src.intelligence.stories import get_story_tracker

    stories = get_story_tracker().recent(limit=limit)
    return {"stories": stories, "total": len(stories)}


@app.get("/api/feeds")
def get_feeds_from_db(
    limit: int = 100,
    only_relevant: bool = False,
    _user=Depends(require_user),
    db=Depends(get_db),
):
    """Get feeds directly from database (for initial load)"""
    try:
        feeds = storage_manager.get_recent_feeds(limit=limit)

        # FIELD_NORMALIZATION + district categorization
        #
        # This whitelist silently dropped region, fake_news_score and
        # llm_filtered. /api/feed (the in-memory copy) carried them and this
        # endpoint did not, so the same event arrived with different fields
        # depending on whether it came from the initial load or a live update --
        # and the sidebar's region filter had nothing to work with until the
        # first websocket push.
        normalized_feeds = []
        for feed in feeds:
            # Ensure frontend-compatible field names
            normalized = {
                "event_id": feed.get("event_id"),
                "summary": feed.get("summary", ""),
                "domain": feed.get("domain", "unknown"),
                "severity": feed.get("severity", "medium"),
                "impact_type": feed.get("impact_type", "risk"),
                "confidence": feed.get("confidence", 0.5),
                "region": feed.get("region", "sri_lanka"),
                "fake_news_score": feed.get("fake_news_score"),
                "llm_filtered": feed.get("llm_filtered", False),
                # Carried explicitly for the same reason as the three above.
                # These rarely survive the round trip -- entities live in the
                # entity store rather than the SQLite row -- so
                # feed_relevance.annotate() hydrates them below. Passing them
                # through here means an event that DOES have them inline is not
                # stripped on the way out.
                "entities": feed.get("entities", []),
                "entities_extracted": feed.get("entities_extracted", False),
                "timestamp": feed.get("timestamp"),
                "district": categorize_feed_by_district(feed)
            }
            normalized_feeds.append(normalized)

        exposure = feed_relevance.load_exposure(db, _user)
        normalized_feeds = feed_relevance.annotate(
            normalized_feeds, exposure, only_relevant=only_relevant
        )

        return {
            "events": normalized_feeds,
            "total": len(normalized_feeds),
            "source": "database",
            "ranked_by_relevance": exposure is not None,
        }
    except Exception as e:
        logger.error(f"[API] Error fetching feeds: {e}")
        return {"events": [], "total": 0, "error": str(e)}


@app.get("/api/feeds/by_district/{district}")
def get_feeds_by_district(district: str, limit: int = 50, _user=Depends(require_user)):
    """Get feeds for specific district"""
    try:
        all_feeds = storage_manager.get_recent_feeds(limit=200)

        # Filter by district
        district_feeds = []
        for feed in all_feeds:
            feed["district"] = categorize_feed_by_district(feed)
            if feed["district"].lower() == district.lower():
                district_feeds.append(feed)
                if len(district_feeds) >= limit:
                    break

        return {
            "district": district,
            "events": district_feeds,
            "total": len(district_feeds)
        }
    except Exception as e:
        logger.error(f"[API] Error fetching district feeds: {e}")
        return {"events": [], "total": 0, "error": str(e)}


@app.get("/api/rivernet")
def get_rivernet_status(_user=Depends(require_user)):
    """Get real-time river monitoring data from RiverNet.lk"""
    try:
        from src.utils.utils import tool_rivernet_status
        river_data = tool_rivernet_status()
        return river_data
    except Exception as e:
        logger.error(f"[API] Error fetching rivernet data: {e}")
        # Must mirror the shape fetch_rivernet_levels actually returns. This
        # used to answer with total_monitored/overall_status/has_alerts -- keys
        # the success path has never produced -- so a client written against the
        # error response read nothing on a good day, and vice versa.
        return {
            "rivers": [],
            "alerts": [],
            "summary": {
                "total_stations": 0,
                "reporting": 0,
                "offline": 0,
                "rising": 0,
                "alerts": 0,
                "flood_alerts": 0,
                "status": "error",
                "regions": [],
            },
            "error": str(e),
        }


@app.get("/api/weather/historical")
def get_historical_climate_data(_user=Depends(require_user)):
    """
    Get 30-year historical flood pattern analysis.
    
    Returns climate trend data including:
    - Average annual rainfall
    - Maximum daily rainfall records
    - Heavy/extreme rain day counts
    - Decadal comparison (1995-2025)
    - Key climate change findings
    """
    try:
        from src.utils.utils import tool_floodwatch_historical
        historical_data = tool_floodwatch_historical()
        return {
            "status": "success",
            "data": historical_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching historical data: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/api/weather/threat")
def get_national_threat_score(_user=Depends(require_user)):
    """
    Get national flood threat score (0-100).
    
    Aggregates river status, DMC alerts, and seasonal factors
    to compute an overall threat level for Sri Lanka.
    
    Returns:
    - national_threat_score (0-100)
    - threat_level (CRITICAL/HIGH/MODERATE/LOW)
    - breakdown by category
    - risk district lists
    """
    try:
        from src.utils.utils import tool_rivernet_status, tool_calculate_national_threat, tool_dmc_alerts

        # Get river data
        river_data = None
        try:
            river_data = tool_rivernet_status()
        except Exception as e:
            logger.warning(f"[ThreatAPI] RiverNet unavailable: {e}")

        # Get DMC alerts
        dmc_data = None
        try:
            dmc_result = tool_dmc_alerts()
            dmc_data = dmc_result.get("alerts", [])
        except Exception as e:
            logger.warning(f"[ThreatAPI] DMC unavailable: {e}")

        # Calculate threat score
        threat_data = tool_calculate_national_threat(
            river_data=river_data,
            dmc_alerts=dmc_data
        )

        return {
            "status": "success",
            **threat_data
        }
    except Exception as e:
        logger.error(f"[API] Error calculating threat: {e}")
        return {
            "status": "error",
            "national_threat_score": 0,
            "threat_level": "UNKNOWN",
            "error": str(e)
        }

# ============================================
# INTEL CONFIG API - User Keywords & Profiles
# ============================================

# Single source of truth for the intel config file.
#
# This used to point at backend/data/intel_config.json -- a file that has never
# existed -- and was then REBOUND further down the module to src/config/. Because
# load/save read the global at call time rather than def time, the live handlers
# ended up reading one path while having been initialised from another. See the
# note on the deleted duplicate handlers below.
INTEL_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "src", "config", "intel_config.json"
)

# Default config structure
DEFAULT_INTEL_CONFIG = {
    "user_profiles": {
        "twitter": [],
        "facebook": [],
        "linkedin": []
    },
    "user_keywords": [],
    "user_products": []
}


def load_intel_config() -> dict:
    """Load intel config from JSON file."""
    try:
        if os.path.exists(INTEL_CONFIG_PATH):
            with open(INTEL_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Intel Config] Error loading config: {e}")
    return DEFAULT_INTEL_CONFIG.copy()


def save_intel_config(config: dict) -> bool:
    """Save intel config to JSON file."""
    try:
        os.makedirs(os.path.dirname(INTEL_CONFIG_PATH), exist_ok=True)
        with open(INTEL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[Intel Config] Error saving config: {e}")
        return False


# Load config on startup
intel_config = load_intel_config()


# NOTE: /api/intel/config GET and POST were ALSO registered here, and because
# Starlette matches routes in registration order, these earlier copies were the
# ones that served every request -- shadowing the correct implementations further
# down the module.
#
# They are removed rather than fixed, because the pair below is already correct.
# The bug they caused:
#
#   The POST merged into the module-global `intel_config` and wrote that out. On
#   a fresh process that global held only the 3-key default (it was loaded from a
#   path that does not exist), so a POST arriving before any GET wrote a 3-key
#   document over the real 8-key file -- silently destroying operational_keywords,
#   alert_thresholds, default_competitors and notes.
#
#   The UI masked this by always GETting on mount. Any direct POST, or a retry
#   after a backend restart, would trigger it.
#
# The surviving handlers read-modify-write the file itself, so they cannot lose
# keys they do not know about.


def get_user_intel_config() -> dict:
    """
    Get the current intel config for use by agents.
    This function is called by social agents to get user-defined keywords and profiles.
    """
    global intel_config
    return intel_config


# ============================================
# SITUATIONAL AWARENESS API ENDPOINTS (NEW)
# ============================================

@app.get("/api/power")
def get_power_status(_user=Depends(require_user)):
    """
    Get CEB power outage / load shedding status.
    
    Returns current power supply status, active load shedding schedules,
    and any CEB announcements.
    """
    try:
        from src.utils.utils import tool_ceb_power_status
        power_data = tool_ceb_power_status()
        return {
            "status": "success",
            **power_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching power status: {e}")
        return {
            "status": "error",
            "load_shedding_active": False,
            "error": str(e)
        }


@app.get("/api/fuel")
def get_fuel_prices(_user=Depends(require_user)):
    """
    Get current fuel prices in Sri Lanka.
    
    Returns prices for Petrol 92/95, Diesel, Super Diesel, and Kerosene.
    """
    try:
        from src.utils.utils import tool_fuel_prices
        fuel_data = tool_fuel_prices()
        return {
            "status": "success",
            **fuel_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching fuel prices: {e}")
        return {
            "status": "error",
            "prices": {},
            "error": str(e)
        }


@app.get("/api/economy")
def get_economic_indicators(_user=Depends(require_user)):
    """
    Get key economic indicators from CBSL.
    
    Returns inflation rates, policy rates, exchange rates, and forex reserves.
    """
    try:
        from src.utils.utils import tool_cbsl_indicators
        economy_data = tool_cbsl_indicators()
        return {
            "status": "success",
            **economy_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching economic indicators: {e}")
        return {
            "status": "error",
            "indicators": {},
            "error": str(e)
        }


@app.get("/api/health")
def get_health_alerts(_user=Depends(require_user)):
    """
    Get health alerts and disease information.
    
    Returns current health alerts, dengue case data, and health advisories.
    """
    try:
        from src.utils.utils import tool_health_alerts
        health_data = tool_health_alerts()
        return {
            "status": "success",
            **health_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching health data: {e}")
        return {
            "status": "error",
            "alerts": [],
            "dengue": {},
            "error": str(e)
        }


@app.get("/api/commodities")
def get_commodity_prices(_user=Depends(require_user)):
    """
    Get prices for essential commodities.
    
    Returns current prices for rice, sugar, dhal, milk powder, and other staples.
    """
    try:
        from src.utils.utils import tool_commodity_prices
        commodity_data = tool_commodity_prices()
        return {
            "status": "success",
            **commodity_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching commodity prices: {e}")
        return {
            "status": "error",
            "commodities": [],
            "error": str(e)
        }


@app.get("/api/water")
def get_water_supply_status(_user=Depends(require_user)):
    """
    Get water supply disruption alerts from NWSDB.
    
    Returns active disruptions, affected areas, and restoration estimates.
    """
    try:
        from src.utils.utils import tool_water_supply_alerts
        water_data = tool_water_supply_alerts()
        return {
            "status": "success",
            **water_data
        }
    except Exception as e:
        logger.error(f"[API] Error fetching water status: {e}")
        return {
            "status": "error",
            "active_disruptions": [],
            "error": str(e)
        }


# NOTE: Weather predictions endpoint moved to async version below (line ~1540)
# NOTE: Currency prediction endpoint moved to async version below (line ~1680)


# NOTE: /api/currency/history was registered twice. This earlier copy shadowed
# the one further down, which is strictly better: it selects the newest data
# file by mtime rather than by lexical filename order, and returns
# daily_return_pct alongside date/close/high/low. Both return
# {status, days, history}, and the frontend reads only status and history,
# so removing this one is transparent to callers.


@app.get("/api/trending")
def get_trending_topics(limit: int = 10, _user=Depends(require_user)):
    """
    Get currently trending topics.
    
    Returns topics with momentum > 2x (gaining traction).
    """
    try:
        from src.utils.trending_detector import get_trending_now, get_spikes
        # Use the global storage_manager instance defined earlier in main.py
        # no need to import it if we are inside main.py function scope where it's visible or passed
        # But since this is a route function, it might need global access or import.
        # Assuming storage_manager is available globally in this file as it was initialized earlier.
        
        trending = get_trending_now(limit=limit)
        spikes = get_spikes()

        # Enrich top 5 trending topics with related feeds
        for topic in trending[:5]:
            keyword = topic["topic"]
            # Search for relevant feeds (limit 2 per topic to keep payload small)
            try:
                related = storage_manager.search_feeds(keyword, limit=2)
                topic["related_feeds"] = related
            except Exception as e:
                logger.warning(f"Error searching feeds for topic {keyword}: {e}")
                topic["related_feeds"] = []

        return {
            "status": "success",
            "trending_topics": trending,
            "spike_alerts": spikes,
            "total_trending": len(trending),
            "total_spikes": len(spikes)
        }

    except Exception as e:
        logger.error(f"[TrendingAPI] Error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "trending_topics": [],
            "spike_alerts": []
        }


@app.get("/api/trending/topic/{topic}")
def get_topic_history(topic: str, hours: int = 24, _user=Depends(require_user)):
    """
    Get hourly mention history for a specific topic.
    
    Args:
        topic: Topic name to get history for
        hours: Number of hours of history to return (default 24)
    """
    try:
        from src.utils.trending_detector import get_trending_detector

        detector = get_trending_detector()
        history = detector.get_topic_history(topic, hours=hours)
        momentum = detector.get_momentum(topic)
        is_spike = detector.is_spike(topic)

        return {
            "status": "success",
            "topic": topic,
            "momentum": momentum,
            "is_spike": is_spike,
            "history": history
        }

    except Exception as e:
        logger.error(f"[TrendingAPI] Error getting history for {topic}: {e}")
        return {
            "status": "error",
            "error": str(e),
            "topic": topic,
            "momentum": 1.0,
            "is_spike": False,
            "history": []
        }


@app.post("/api/trending/record")
def record_topic_mention(topic: str, source: str = "manual", domain: str = "general", _user=Depends(require_user)):
    """
    Record a topic mention (for testing/manual tracking).
    
    Args:
        topic: Topic/keyword being mentioned
        source: Source of the mention (twitter, news, etc.)
        domain: Domain category (political, economical, etc.)
    """
    try:
        from src.utils.trending_detector import record_topic_mention as record_mention

        record_mention(topic=topic, source=source, domain=domain)

        # Get updated momentum
        from src.utils.trending_detector import get_trending_detector
        detector = get_trending_detector()
        momentum = detector.get_momentum(topic)

        return {
            "status": "success",
            "message": f"Recorded mention for '{topic}'",
            "current_momentum": momentum,
            "is_spike": detector.is_spike(topic)
        }

    except Exception as e:
        logger.error(f"[TrendingAPI] Error recording mention: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================
# ANOMALY DETECTION ENDPOINTS
# ============================================

# Lazy-loaded anomaly detection components
#
# WHY THIS IS NOT THE ORIGINAL PER-LANGUAGE LOADER
# ------------------------------------------------
# The committed isolation_forest_{english,tamil}.joblib models take 768-dim
# distilBERT vectors from models/anomaly-detection/src/utils/vectorizer.py.
# That vectorizer needs transformers + torch, which requirements-service.txt
# deliberately does not install (they are ~3 GB and OOM a 512 MB instance).
#
# It does not fail when they are absent. It logs and returns np.zeros(768).
# Measured with transformers and torch blocked exactly as the deployed image
# has them, every event scored identically:
#
#     nonzero_dims=0  pred=-1  score=+0.012138   Heavy flooding in Ratnapura...
#     nonzero_dims=0  pred=-1  score=+0.012138   Colombo Port operating normally...
#     nonzero_dims=0  pred=-1  score=+0.012138   Central Bank holds rate steady...
#
# Everything flagged anomalous, one constant score, and the endpoint reporting
# model_status "ml_active" throughout. That is a fabricated result presented as
# inference, which is worse than reporting nothing.
#
# So: the production path uses 384-dim all-MiniLM-L6-v2 ONNX embeddings, which
# chromadb already ships and the slim image already carries, with an isolation
# forest re-fitted on those (scripts/train_anomaly_minilm.py). The 768-dim
# models are still used when transformers really is installed -- local dev --
# but they are never fed a zero vector to keep up appearances.
_anomaly_models = {}  # {language: model}
_anomaly_mode = None  # "minilm" | "bert" | None
_vectorizer = None
_language_detector = None

_MINILM_MODEL = "isolation_forest_minilm.joblib"


def _bert_vectorizer_usable() -> bool:
    """
    True only when the 768-dim path can produce real vectors.

    Checked by import rather than by trying it, because trying it returns
    zeros rather than raising -- which is the entire problem.
    """
    import importlib.util

    return all(importlib.util.find_spec(m) for m in ("transformers", "torch"))


def _load_anomaly_components():
    """
    Load whichever anomaly model this environment can actually run.

    Returns False when none can run, which routes the endpoints to their
    labelled heuristic scoring rather than to a model fed garbage.
    """
    global _anomaly_models, _anomaly_mode, _vectorizer, _language_detector

    if _anomaly_models:
        return True

    try:
        import joblib
        from pathlib import Path

        models_root = Path(__file__).parent.parent / "models" / "anomaly-detection"
        output_dir = models_root / "output"
        artifacts_dir = models_root / "artifacts" / "model_trainer"

        # --- preferred: MiniLM, which runs anywhere the API runs ------------
        for search_dir in (artifacts_dir, output_dir):
            minilm_path = search_dir / _MINILM_MODEL
            if not minilm_path.exists():
                continue
            try:
                from src import embeddings

                if not embeddings.available():
                    logger.warning("[AnomalyAPI] MiniLM model present but embedder unavailable")
                    break

                _anomaly_models["minilm"] = joblib.load(minilm_path)
                _anomaly_mode = "minilm"
                _vectorizer = lambda texts: embeddings.embed(texts)  # noqa: E731
                _language_detector = None
                logger.info(
                    "[AnomalyAPI] anomaly detection active: %s on %d-dim ONNX MiniLM",
                    minilm_path.name, embeddings.EMBEDDING_DIM,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AnomalyAPI] could not load %s: %s", minilm_path.name, exc)
                _anomaly_models.pop("minilm", None)
                break

        # --- legacy 768-dim path, only when it can genuinely run ------------
        if not _bert_vectorizer_usable():
            logger.warning(
                "[AnomalyAPI] no MiniLM model and transformers/torch are not "
                "installed, so the 768-dim models would score zero vectors. "
                "Falling back to labelled heuristic scoring. Build the "
                "production model with: python scripts/train_anomaly_minilm.py"
            )
            return False

        for lang in ["english", "sinhala", "tamil"]:
            for search_dir in [artifacts_dir, output_dir]:
                model_path = search_dir / f"isolation_forest_{lang}.joblib"
                if model_path.exists():
                    _anomaly_models[lang] = joblib.load(model_path)
                    logger.info(f"[AnomalyAPI] Loaded {lang} model from {model_path.name}")
                    break

        if not _anomaly_models:
            legacy_paths = [
                output_dir / "isolation_forest_embeddings_only.joblib",
                output_dir / "isolation_forest_model.joblib",
            ]
            for legacy_path in legacy_paths:
                if legacy_path.exists():
                    _anomaly_models["english"] = joblib.load(legacy_path)
                    logger.info(f"[AnomalyAPI] Loaded legacy model: {legacy_path.name}")
                    break

        if not _anomaly_models:
            logger.warning("[AnomalyAPI] No trained models found. Run training first.")
            return False

        from models.anomaly_detection.src.utils.vectorizer import get_vectorizer
        from models.anomaly_detection.src.utils.language_detector import detect_language

        _vectorizer = get_vectorizer()
        _language_detector = detect_language
        _anomaly_mode = "bert"

        logger.info(f"[AnomalyAPI] ✓ Loaded models for: {list(_anomaly_models.keys())}")
        return True

    except Exception as e:
        logger.error(f"[AnomalyAPI] Failed to load components: {e}")
        return False


def _score_texts(texts):
    """
    Score a batch, returning [(prediction, raw_score), ...].

    One code path for both endpoints so they cannot drift apart, and one place
    that knows the embedding width must match the fitted model.
    """
    import numpy as np

    if _anomaly_mode == "minilm":
        vectors = np.array(_vectorizer(list(texts)))
        model = _anomaly_models["minilm"]
        preds = model.predict(vectors)
        scores = -model.decision_function(vectors)
        return [(int(p), float(s)) for p, s in zip(preds, scores)], "isolation_forest_minilm"

    out = []
    for text in texts:
        lang, _ = _language_detector(text)
        vector = _vectorizer.vectorize(text, lang)
        model = _anomaly_models.get(lang) or _anomaly_models.get("english")
        if model is None:
            out.append((1, 0.0))
            continue
        out.append((
            int(model.predict([vector])[0]),
            float(-model.decision_function([vector])[0]),
        ))
    return out, "isolation_forest_bert"


@app.post("/api/predict")
def predict_anomaly(texts: List[str] = None, text: str = None, _user=Depends(require_user)):
    """
    Run anomaly detection on text(s) using per-language models.
    
    Args:
        texts: List of texts to analyze
        text: Single text to analyze (alternative to texts)
    
    Returns:
        Predictions with anomaly scores
    """
    try:
        # Handle input
        if text and not texts:
            texts = [text]

        if not texts:
            return {"error": "No text provided. Use 'text' or 'texts' field.", "predictions": []}

        # Load components
        if not _load_anomaly_components():
            # If no model, return scores based on heuristics
            return {
                "predictions": [
                    {
                        "text": t[:100] + "..." if len(t) > 100 else t,
                        "is_anomaly": False,
                        "anomaly_score": 0.0,
                        "method": "heuristic"
                    }
                    for t in texts
                ],
                "model_status": "not_trained",
                "message": "Model not trained yet. Using default scores."
            }

        # One scoring path shared with /api/anomalies. A failure here reports
        # itself rather than degrading to zeros: a 0.0 anomaly score is
        # indistinguishable from a confident "this is normal".
        try:
            scored, method = _score_texts(texts)
        except Exception as e:
            logger.error(f"[AnomalyAPI] scoring failed: {e}", exc_info=True)
            return {
                "predictions": [],
                "total": 0,
                "model_status": "error",
                "message": f"Scoring failed: {e}",
            }

        predictions = [
            {
                "text": t[:100] + "..." if len(t) > 100 else t,
                "is_anomaly": prediction == -1,
                "anomaly_score": round(score, 6),
                "method": method,
            }
            for t, (prediction, score) in zip(texts, scored)
        ]

        return {
            "predictions": predictions,
            "total": len(predictions),
            "anomalies_found": sum(1 for p in predictions if p.get("is_anomaly")),
            "model_status": "loaded",
            "embedding": _anomaly_mode,
            "models_available": list(_anomaly_models.keys())
        }

    except Exception as e:
        logger.error(f"[AnomalyAPI] Predict error: {e}", exc_info=True)
        return {"error": str(e), "predictions": []}


@app.get("/api/anomalies")
def get_anomalies(limit: int = 20, threshold: float = 0.5, _user=Depends(require_user)):
    """
    Get recent feeds that are flagged as anomalies.
    
    Args:
        limit: Max number of results
        threshold: Anomaly score threshold (0-1)
    
    Returns:
        List of anomalous events
    """
    try:
        # Get recent feeds
        feeds = storage_manager.get_recent_feeds(limit=100)

        if not feeds:
            # No feeds yet - return helpful message
            return {
                "anomalies": [],
                "total": 0,
                "model_status": "no_data",
                "message": "No feed data available yet. Wait for graph execution to complete."
            }

        # Prefer the standalone anomaly service. Feeds stay here (storage is local
        # to the backend); only scoring is delegated.
        remote = model_gateway.call_sync(
            "anomaly",
            "/detect",
            method="POST",
            json_body={"feeds": feeds, "threshold": threshold, "limit": limit},
        )
        if remote is not None:
            return remote

        if not _load_anomaly_components():
            # Use severity + keyword-based scoring as intelligent fallback
            anomalies = []
            anomaly_keywords = ["emergency", "crisis", "breaking", "urgent", "alert", 
                               "warning", "critical", "disaster", "flood", "protest"]

            for f in feeds:
                score = 0.0
                summary = str(f.get("summary", "")).lower()
                severity = f.get("severity", "low")

                # Severity-based scoring
                if severity == "critical": score = 0.9
                elif severity == "high": score = 0.75
                elif severity == "medium": score = 0.5
                else: score = 0.25

                # Keyword boosting
                keyword_matches = sum(1 for kw in anomaly_keywords if kw in summary)
                if keyword_matches > 0:
                    score = min(1.0, score + (keyword_matches * 0.1))

                # Only include if above threshold
                if score >= threshold:
                    anomalies.append({
                        **f,
                        "anomaly_score": round(score, 3),
                        "is_anomaly": score >= 0.7
                    })

            # Sort by anomaly score
            anomalies.sort(key=lambda x: x.get("anomaly_score", 0), reverse=True)

            return {
                "anomalies": anomalies[:limit],
                "total": len(anomalies),
                "threshold": threshold,
                "model_status": "fallback_scoring",
                "method": "severity + keyword heuristic",
                "is_ml": False,
                "message": (
                    "Heuristic scoring, not a model: severity weighting plus "
                    "keyword matches. No ML inference is running."
                ),
            }

        # --- real model inference -------------------------------------------
        scorable = [f for f in feeds if str(f.get("summary", "")).strip()]
        if not scorable:
            return {"anomalies": [], "total": 0, "threshold": threshold,
                    "model_status": "no_events", "is_ml": True}

        try:
            scored, method = _score_texts([f["summary"] for f in scorable])
        except Exception as e:
            # Do not fall through to a model-shaped answer that isn't one.
            logger.error(f"[AnomalyAPI] scoring failed: {e}", exc_info=True)
            return {
                "anomalies": [], "total": 0, "threshold": threshold,
                "model_status": "error", "is_ml": False,
                "message": f"Model inference failed: {e}",
            }

        anomalies = []
        for feed, (prediction, raw) in zip(scorable, scored):
            # decision_function is roughly [-0.5, 0.5] around the fitted
            # boundary; shifting by 0.5 puts it on a 0-1 scale for the UI while
            # keeping the raw value for anyone who wants to see it.
            normalized = max(0.0, min(1.0, raw + 0.5))
            if prediction == -1 or normalized >= threshold:
                anomalies.append({
                    **feed,
                    "anomaly_score": float(round(normalized, 3)),
                    "raw_score": round(raw, 6),
                    "is_anomaly": prediction == -1,
                    "detection_method": method,
                })

        anomalies.sort(key=lambda x: x.get("anomaly_score", 0), reverse=True)

        return {
            "anomalies": anomalies[:limit],
            "total": len(anomalies),
            "scored": len(scorable),
            "threshold": threshold,
            "model_status": "ml_active",
            "is_ml": True,
            "embedding": _anomaly_mode,
            "models_loaded": list(_anomaly_models.keys()),
        }

    except Exception as e:
        logger.error(f"[AnomalyAPI] Get anomalies error: {e}")
        return {"anomalies": [], "total": 0, "error": str(e)}


@app.get("/api/model/status")
def get_model_status(_user=Depends(require_user)):
    """Get anomaly detection model status"""
    try:
        from pathlib import Path

        models_root = Path(__file__).parent.parent / "models" / "anomaly-detection"
        output_dir = models_root / "output"
        artifacts_dir = models_root / "artifacts" / "model_trainer"

        models_found = []
        for directory in (artifacts_dir, output_dir):
            if directory.exists():
                models_found.extend(f.name for f in directory.glob("*.joblib"))

        # Load lazily so this reports what would actually happen on a request,
        # rather than "not loaded" simply because nobody has asked yet.
        loaded = _load_anomaly_components()

        # What the model was fitted on. Written by
        # scripts/train_anomaly_minilm.py; absent for the legacy 768-dim models,
        # which is itself worth knowing.
        training_card = None
        card_path = artifacts_dir / "isolation_forest_minilm.json"
        if card_path.exists():
            try:
                training_card = json.loads(card_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                training_card = None

        return {
            "model_loaded": loaded,
            "embedding": _anomaly_mode,
            "inference": (
                "in-process (this container)" if loaded
                else "unavailable -- endpoints use labelled heuristic scoring"
            ),
            "models_available": sorted(set(models_found)),
            "vectorizer_loaded": _vectorizer is not None,
            "batch_threshold": int(os.getenv("BATCH_THRESHOLD", "1000")),
            "output_directory": str(output_dir),
            "training": model_metadata.staleness("anomaly"),
            "training_card": training_card,
        }

    except Exception as e:
        return {"error": str(e), "model_loaded": False}


# ============================================
# RAG CHATBOT ENDPOINTS
# ============================================

# Lazy-loaded RAG instance
# RAG instances, keyed by user.
#
# This was a single process-global. RogerRAG carries chat_history on the
# instance (src/rag.py), so one shared instance means every caller appends to
# and reads from the SAME conversation. Single-tenant that was merely odd;
# multi-user it is a cross-user leak -- user B's next question arrives with
# user A's conversation as context, and /api/rag/clear wipes it for everyone.
#
# An LRU cap matters more than it looks: each instance holds an unbounded
# history, and this runs in a 512 MB container.
_rag_instances: "OrderedDict[str, Any]" = None  # type: ignore[assignment]
_rag_lock = threading.Lock()
_RAG_MAX_INSTANCES = 8
_RAG_MAX_HISTORY = 20        # turns retained per user


def _get_rag(user_key: str = "anonymous"):
    """Get or create this user's RAG instance."""
    global _rag_instances
    from collections import OrderedDict

    with _rag_lock:
        if _rag_instances is None:
            _rag_instances = OrderedDict()

        existing = _rag_instances.get(user_key)
        if existing is not None:
            _rag_instances.move_to_end(user_key)
            # Keep history bounded; RogerRAG appends without a limit.
            history = getattr(existing, "chat_history", None)
            if isinstance(history, list) and len(history) > _RAG_MAX_HISTORY:
                del history[:-_RAG_MAX_HISTORY]
            return existing

        try:
            from src.rag import RogerRAG
            instance = RogerRAG()
        except Exception as e:
            logger.error(f"[RAG API] Failed to initialize RAG: {e}")
            return None

        _rag_instances[user_key] = instance
        while len(_rag_instances) > _RAG_MAX_INSTANCES:
            evicted, _ = _rag_instances.popitem(last=False)
            logger.info("[RAG API] evicted RAG instance for %s (LRU)", evicted)

        logger.info("[RAG API] ✓ RAG instance initialized for %s", user_key)
        return instance


def _rag_key(user) -> str:
    """Conversation scope. Falls back to a shared scope when auth is off."""
    return getattr(user, "id", None) or "anonymous"


def _optional_user(*args, **kwargs):
    """
    Resolve the caller when auth is available, else None.

    Indirection so the RAG endpoints work whether or not the auth package
    imported -- bootstrap deliberately degrades rather than taking down a
    service that ran fine without it.
    """
    return None


if _AUTH_READY:
    try:
        from auth.dependencies import optional_user as _optional_user  # noqa: F811
    except Exception:  # pragma: no cover
        logger.warning("[RAG API] auth dependency unavailable; chats share one scope")




class ChatRequest(BaseModel):
    message: str
    domain_filter: Optional[str] = None
    use_history: bool = True


class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []
    reformulated: Optional[str] = None
    docs_found: int = 0
    error: Optional[str] = None


@app.post("/api/rag/chat", response_model=ChatResponse)
def rag_chat(request: ChatRequest, _user=Depends(require_user)):
    """
    Chat with the RAG system.
    
    Args:
        message: User's question
        domain_filter: Optional domain (political, economic, weather, social, intelligence)
        use_history: Whether to use chat history for context (default: True)
    
    Returns:
        AI response with sources
    """
    try:
        rag = _get_rag(_rag_key(_user))
        if not rag:
            return ChatResponse(
                answer="RAG system not available. Please check server logs.",
                error="RAG initialization failed"
            )

        result = rag.query(
            question=request.message,
            domain_filter=request.domain_filter,
            use_history=request.use_history
        )

        return ChatResponse(
            answer=result.get("answer", "No response generated."),
            sources=result.get("sources", []),
            reformulated=result.get("reformulated"),
            docs_found=result.get("docs_found", 0),
            error=result.get("error")
        )

    except Exception as e:
        logger.error(f"[RAG API] Chat error: {e}", exc_info=True)
        return ChatResponse(
            answer=f"Error processing your request: {str(e)}",
            error=str(e)
        )


@app.get("/api/rag/stats")
def rag_stats(_user=Depends(require_user)):
    """Get RAG system statistics"""
    try:
        rag = _get_rag()
        if not rag:
            return {"error": "RAG not available", "status": "offline"}

        stats = rag.get_stats()
        stats["status"] = "online"
        return stats

    except Exception as e:
        return {"error": str(e), "status": "error"}


@app.post("/api/rag/clear")
def rag_clear_history(_user=Depends(require_user)):
    """Clear RAG chat history"""
    try:
        rag = _get_rag(_rag_key(_user))
        if rag:
            rag.clear_history()
            return {"message": "Chat history cleared", "success": True}
        return {"message": "RAG not available", "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}


# =============================================================================
# INTELLIGENCE CONFIG ENDPOINTS (User-defined monitoring targets)
# =============================================================================

# INTEL_CONFIG_PATH is defined once, near the top of this module. It used to be
# rebound here to a different path, which is what split reads from writes.


def _ensure_intel_config() -> str:
    """Ensure config directory and file exist with default structure"""
    os.makedirs(os.path.dirname(INTEL_CONFIG_PATH), exist_ok=True)
    if not os.path.exists(INTEL_CONFIG_PATH):
        default_config = {
            "user_profiles": {"twitter": [], "facebook": [], "linkedin": []},
            "user_keywords": [],
            "user_products": []
        }
        with open(INTEL_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2)
        logger.info(f"[IntelConfig] Created default config at {INTEL_CONFIG_PATH}")
    return INTEL_CONFIG_PATH


@app.get("/api/intel/config")
def get_intel_config(_user=Depends(require_user)):
    """
    Get current intelligence monitoring configuration.
    
    Returns user-defined profiles, keywords, and products that the
    Intelligence Agent monitors in addition to defaults.
    """
    try:
        path = _ensure_intel_config()
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return {"status": "success", "config": config}
    except Exception as e:
        logger.error(f"[IntelConfig] Error reading config: {e}")
        return {"status": "error", "error": str(e)}


class IntelConfigUpdate(BaseModel):
    user_profiles: Optional[Dict[str, List[str]]] = None
    user_keywords: Optional[List[str]] = None
    user_products: Optional[List[str]] = None


@app.post("/api/intel/config")
def update_intel_config(config: IntelConfigUpdate, _user=Depends(require_user)):
    """
    Update intelligence monitoring configuration.
    
    Replaces the entire user config with the provided values.
    """
    try:
        path = _ensure_intel_config()

        # Read existing config
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f)

        # Update with provided values
        if config.user_profiles is not None:
            existing["user_profiles"] = config.user_profiles
        if config.user_keywords is not None:
            existing["user_keywords"] = config.user_keywords
        if config.user_products is not None:
            existing["user_products"] = config.user_products

        # Save
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)

        logger.info(f"[IntelConfig] Updated config: {len(existing.get('user_keywords', []))} keywords, {sum(len(v) for v in existing.get('user_profiles', {}).values())} profiles")
        return {"status": "updated", "config": existing}

    except Exception as e:
        logger.error(f"[IntelConfig] Error updating config: {e}")
        return {"status": "error", "error": str(e)}


@app.post("/api/intel/config/add")
def add_intel_target(target_type: str, value: str, platform: Optional[str] = None, _user=Depends(require_user)):
    """
    Add a single monitoring target.
    
    Args:
        target_type: "keyword", "product", or "profile"
        value: The value to add
        platform: Required for "profile" type (twitter, facebook, linkedin)
    
    Example:
        POST /api/intel/config/add?target_type=keyword&value=Colombo+Port
        POST /api/intel/config/add?target_type=profile&value=CompetitorX&platform=twitter
    """
    try:
        path = _ensure_intel_config()
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        added = False

        if target_type == "keyword":
            if value not in config.get("user_keywords", []):
                config.setdefault("user_keywords", []).append(value)
                added = True
        elif target_type == "product":
            if value not in config.get("user_products", []):
                config.setdefault("user_products", []).append(value)
                added = True
        elif target_type == "profile":
            if not platform:
                return {"status": "error", "error": "platform is required for profile type"}
            profiles = config.setdefault("user_profiles", {})
            platform_list = profiles.setdefault(platform, [])
            if value not in platform_list:
                platform_list.append(value)
                added = True
        else:
            return {"status": "error", "error": f"Invalid target_type: {target_type}"}

        if added:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            logger.info(f"[IntelConfig] Added {target_type}: {value}")

        return {"status": "added" if added else "already_exists", "config": config}

    except Exception as e:
        logger.error(f"[IntelConfig] Error adding target: {e}")
        return {"status": "error", "error": str(e)}


@app.delete("/api/intel/config/remove")
def remove_intel_target(target_type: str, value: str, platform: Optional[str] = None, _user=Depends(require_user)):
    """
    Remove a monitoring target.
    
    Args:
        target_type: "keyword", "product", or "profile"
        value: The value to remove
        platform: Required for "profile" type
    """
    try:
        path = _ensure_intel_config()
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        removed = False

        if target_type == "keyword":
            if value in config.get("user_keywords", []):
                config["user_keywords"].remove(value)
                removed = True
        elif target_type == "product":
            if value in config.get("user_products", []):
                config["user_products"].remove(value)
                removed = True
        elif target_type == "profile":
            if not platform:
                return {"status": "error", "error": "platform is required for profile type"}
            if platform in config.get("user_profiles", {}) and value in config["user_profiles"][platform]:
                config["user_profiles"][platform].remove(value)
                removed = True
        else:
            return {"status": "error", "error": f"Invalid target_type: {target_type}"}

        if removed:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            logger.info(f"[IntelConfig] Removed {target_type}: {value}")

        return {"status": "removed" if removed else "not_found", "config": config}

    except Exception as e:
        logger.error(f"[IntelConfig] Error removing target: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# WEATHER PREDICTION ENDPOINTS
# =============================================================================

# Lazy-loaded weather predictor
_weather_predictor = None

def get_weather_predictor():
    """Lazy-load the weather predictor using isolated import."""
    global _weather_predictor
    if _weather_predictor is not None:
        return _weather_predictor

    try:
        import importlib.util
        from pathlib import Path
        import json

        # Use importlib.util for fully isolated import (avoids package collisions)
        weather_src = Path(__file__).parent.parent / "models" / "weather-prediction" / "src"
        predictor_path = weather_src / "components" / "predictor.py"

        if not predictor_path.exists():
            logger.error(f"[WeatherAPI] predictor.py not found at {predictor_path}")
            return None

        # CRITICAL: Remove any conflicting paths (currency-volatility-prediction/src)
        # to avoid entity.config_entity collision
        currency_src = str(Path(__file__).parent.parent / "models" / "currency-volatility-prediction" / "src")
        stock_src = str(Path(__file__).parent.parent / "models" / "stock-price-prediction" / "src")
        anomaly_src = str(Path(__file__).parent.parent / "models" / "anomaly-detection" / "src")
        
        original_path = sys.path.copy()
        sys.path = [p for p in sys.path if currency_src not in p and stock_src not in p and anomaly_src not in p]
        
        # CRITICAL: Clear cached entity modules that may have been imported from wrong path
        modules_to_clear = [k for k in sys.modules.keys() if 'entity' in k.lower() or 'config_entity' in k.lower()]
        saved_modules = {}
        for mod_name in modules_to_clear:
            saved_modules[mod_name] = sys.modules.pop(mod_name, None)
        
        # Add weather src to path FIRST for relative imports
        weather_src_str = str(weather_src)
        if weather_src_str not in sys.path:
            sys.path.insert(0, weather_src_str)

        try:
            # Now load predictor module
            spec = importlib.util.spec_from_file_location(
                "weather_predictor_module",
                str(predictor_path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            _weather_predictor = module.WeatherPredictor()
            logger.info("[WeatherAPI] ✓ Weather predictor initialized via isolated import")
        finally:
            # Restore original path
            sys.path = original_path
            # Restore saved modules (to avoid breaking other parts of the system)
            for mod_name, mod in saved_modules.items():
                if mod is not None:
                    sys.modules[mod_name] = mod

        return _weather_predictor


    except Exception as e:
        logger.error(f"[WeatherAPI] Failed to initialize predictor: {e}")
        import traceback
        logger.error(f"[WeatherAPI] Full traceback:\n{traceback.format_exc()}")
        return None


@app.get("/api/weather/predictions")
async def get_weather_predictions(_user=Depends(require_user)):
    """
    Get weather predictions for all 25 Sri Lankan districts.
    
    Returns next-day predictions including:
    - Temperature (high/low)
    - Rainfall (amount and probability)
    - Flood risk
    - Severity classification
    """
    # Prefer the standalone weather service when WEATHER_SERVICE_URL is set;
    # fall through to the in-process predictor otherwise (or if it is down).
    remote = await model_gateway.call("weather", "/predict")
    if remote is not None:
        # Predictions carry their model's training cutoff, so the card
        # can warn without a second request.
        return model_metadata.annotate(remote, "weather")

    predictor = get_weather_predictor()

    if predictor is None:
        return {
            "status": "unavailable",
            "message": "Weather prediction model not loaded",
            "predictions": None,
            "training": model_metadata.staleness("weather"),
        }

    try:
        # Try to get latest predictions from file
        predictions = predictor.get_latest_predictions()

        if predictions is None:
            # Generate new predictions
            logger.info("[WeatherAPI] Generating new predictions...")
            predictions = predictor.predict_all_districts()
            predictor.save_predictions(predictions)

        return {
            "status": "success",
            "prediction_date": predictions.get("prediction_date"),
            "generated_at": predictions.get("generated_at"),
            "districts": predictions.get("districts", {}),
            "total_districts": len(predictions.get("districts", {}))
        }
    except Exception as e:
        logger.error(f"[WeatherAPI] Error getting predictions: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/weather/predictions/{district}")
async def get_district_weather(district: str, _user=Depends(require_user)):
    """Get weather prediction for a specific district."""
    remote = await model_gateway.call("weather", f"/predict/{district}")
    if remote is not None:
        return remote

    predictor = get_weather_predictor()

    if predictor is None:
        return {"status": "unavailable", "message": "Weather predictor not loaded"}

    try:
        predictions = predictor.get_latest_predictions()

        if predictions is None:
            predictions = predictor.predict_all_districts()

        districts = predictions.get("districts", {})

        # Case-insensitive lookup
        district_key = None
        for d in districts.keys():
            if d.lower() == district.lower():
                district_key = d
                break

        if district_key is None:
            return {
                "status": "not_found",
                "message": f"District '{district}' not found",
                "available_districts": list(districts.keys())
            }

        return {
            "status": "success",
            "district": district_key,
            "prediction_date": predictions.get("prediction_date"),
            "prediction": districts[district_key]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/weather/model/status")
async def get_weather_model_status(_user=Depends(require_user)):
    """Get weather prediction model status and training info."""
    remote = await model_gateway.call("weather", "/model/status")
    if remote is not None:
        return model_metadata.annotate(remote, "weather")

    from pathlib import Path

    models_dir = Path(__file__).parent.parent / "models" / "weather-prediction" / "artifacts" / "models"
    predictions_dir = Path(__file__).parent.parent / "models" / "weather-prediction" / "output" / "predictions"

    model_files = list(models_dir.glob("lstm_*.h5")) if models_dir.exists() else []
    prediction_files = list(predictions_dir.glob("predictions_*.json")) if predictions_dir.exists() else []

    latest_prediction = None
    if prediction_files:
        latest = max(prediction_files, key=lambda p: p.stat().st_mtime)
        latest_prediction = {
            "file": latest.name,
            "modified": datetime.fromtimestamp(latest.stat().st_mtime).isoformat()
        }

    return {
        "status": "available" if model_files else "not_trained",
        "models_trained": len(model_files),
        "trained_stations": [f.stem.replace("lstm_", "").upper() for f in model_files],
        "latest_prediction": latest_prediction,
        "predictions_available": len(prediction_files),
        "training": model_metadata.staleness("weather"),
    }


# =============================================================================
# CURRENCY PREDICTION ENDPOINTS
# =============================================================================

# Lazy-loaded currency predictor
_currency_predictor = None

def get_currency_predictor():
    """Lazy-load the currency predictor."""
    global _currency_predictor
    if _currency_predictor is None:
        try:
            import sys
            from pathlib import Path
            currency_path = Path(__file__).parent.parent / "models" / "currency-volatility-prediction" / "src"
            sys.path.insert(0, str(currency_path))
            from components.predictor import CurrencyPredictor
            _currency_predictor = CurrencyPredictor()
            logger.info("[CurrencyAPI] Currency predictor initialized")
        except Exception as e:
            logger.warning(f"[CurrencyAPI] Failed to initialize predictor: {e}")
            _currency_predictor = None
    return _currency_predictor


@app.get("/api/currency/prediction")
async def get_currency_prediction(_user=Depends(require_user)):
    """
    Get USD/LKR currency prediction for next day.
    
    Returns:
    - Current rate
    - Predicted rate
    - Expected change percentage
    - Direction (strengthening/weakening)
    - Volatility classification
    """
    remote = await model_gateway.call("currency", "/predict")
    if remote is not None:
        # Predictions carry their model's training cutoff, so the card
        # can warn without a second request.
        return model_metadata.annotate(remote, "currency")

    predictor = get_currency_predictor()

    if predictor is None:
        # No model. What follows is NOT a prediction -- there is nothing
        # predicting. It used to draw a number from np.random.normal() around a
        # hardcoded 298.0 and return it as {"status": "success"} with a
        # direction and a volatility class, indistinguishable from real model
        # output. The rate has since moved to ~335, so even the anchor was
        # wrong by 12%.
        #
        # Now: report the real spot rate, and state plainly that no forecast is
        # available rather than inventing one.
        from src.utils.utils import fetch_usd_lkr

        fx = fetch_usd_lkr()
        current_rate = fx["usd_lkr"] if fx else None

        return {
            "status": "unavailable",
            "message": (
                "The currency model is not loaded, so no forecast is available. "
                "The rate shown is the current spot rate, not a prediction."
            ),
            "prediction": {
                "generated_at": datetime.now().isoformat(),
                "model_version": "none",
                "is_fallback": True,
                "current_rate": current_rate,
                "rate_as_of": fx["as_of"] if fx else None,
                "predicted_rate": None,
                "expected_change": None,
                "expected_change_pct": None,
                "direction": fx["trend"] if fx else None,
                "volatility_class": None,
                "note": "No model loaded - spot rate only, no forecast",
            },
            "training": model_metadata.staleness("currency"),
        }

    try:
        # Try to get latest prediction from file
        prediction = predictor.get_latest_prediction()

        if prediction is None:
            # Generate fallback
            logger.info("[CurrencyAPI] No prediction found, generating fallback...")
            prediction = predictor.generate_fallback_prediction()
            predictor.save_prediction(prediction)

        return {
            "status": "success",
            "prediction": prediction,
            "training": model_metadata.staleness("currency"),
        }
    except Exception as e:
        logger.error(f"[CurrencyAPI] Error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/currency/history")
async def get_currency_history(days: int = 30, _user=Depends(require_user)):
    """Get historical USD/LKR rates."""
    from pathlib import Path
    import pandas as pd

    try:
        data_dir = Path(__file__).parent.parent / "models" / "currency-volatility-prediction" / "artifacts" / "data"
        csv_files = list(data_dir.glob("currency_data_*.csv")) if data_dir.exists() else []

        if not csv_files:
            return {"status": "no_data", "message": "No currency data available"}

        latest = max(csv_files, key=lambda p: p.stat().st_mtime)
        df = pd.read_csv(latest, parse_dates=["date"])

        # Get last N days
        df = df.tail(days)

        history = []
        for _, row in df.iterrows():
            history.append({
                "date": row["date"].strftime("%Y-%m-%d") if hasattr(row["date"], "strftime") else str(row["date"]),
                "close": round(row["close"], 2),
                "high": round(row.get("high", row["close"]), 2),
                "low": round(row.get("low", row["close"]), 2),
                "daily_return_pct": round(row.get("daily_return", 0) * 100, 3)
            })

        return {
            "status": "success",
            "days": len(history),
            "history": history
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/currency/model/status")
async def get_currency_model_status(_user=Depends(require_user)):
    """Get currency prediction model status."""
    remote = await model_gateway.call("currency", "/model/status")
    if remote is not None:
        return model_metadata.annotate(remote, "currency")

    from pathlib import Path

    models_dir = Path(__file__).parent.parent / "models" / "currency-volatility-prediction" / "artifacts" / "models"
    predictions_dir = Path(__file__).parent.parent / "models" / "currency-volatility-prediction" / "output" / "predictions"

    model_exists = (models_dir / "gru_usd_lkr.h5").exists() if models_dir.exists() else False
    prediction_files = list(predictions_dir.glob("currency_prediction_*.json")) if predictions_dir.exists() else []

    latest_prediction = None
    if prediction_files:
        latest = max(prediction_files, key=lambda p: p.stat().st_mtime)
        latest_prediction = {
            "file": latest.name,
            "modified": datetime.fromtimestamp(latest.stat().st_mtime).isoformat()
        }

    return {
        "status": "available" if model_exists else "not_trained",
        "model_type": "GRU",
        "target": "USD/LKR",
        "latest_prediction": latest_prediction,
        "predictions_available": len(prediction_files),
        "training": model_metadata.staleness("currency"),
    }


# =============================================================================
# STOCK PREDICTION ENDPOINTS
# =============================================================================

# Lazy-loaded stock predictor
_stock_predictor = None

def get_stock_predictor():
    """Lazy-load the stock predictor."""
    global _stock_predictor
    if _stock_predictor is None:
        try:
            import sys
            from pathlib import Path
            stock_path = Path(__file__).parent.parent / "models" / "stock-price-prediction" / "src"
            sys.path.insert(0, str(stock_path))
            from components.predictor import StockPredictor
            _stock_predictor = StockPredictor()
            logger.info("[StockAPI] Stock predictor initialized")
        except Exception as e:
            logger.warning(f"[StockAPI] Failed to initialize predictor: {e}")
            _stock_predictor = None
    return _stock_predictor


@app.get("/api/stocks/predictions")
async def get_stock_predictions(_user=Depends(require_user)):
    """
    Get stock price predictions for all configured stocks.
    
    Returns predictions for 10 popular stocks with:
    - Current price
    - Predicted next-day price
    - Expected change percentage
    - Trend classification (bullish/bearish/neutral)
    - Model architecture used
    """
    remote = await model_gateway.call("stock", "/predict")
    if remote is not None:
        # Predictions carry their model's training cutoff, so the card
        # can warn without a second request.
        return model_metadata.annotate(remote, "stock")

    predictor = get_stock_predictor()

    if predictor is None:
        # Generate fallback even without predictor
        try:
            import sys
            from pathlib import Path
            stock_path = Path(__file__).parent.parent / "models" / "stock-price-prediction" / "src"
            sys.path.insert(0, str(stock_path))
            from constants.training_pipeline import STOCKS_TO_TRAIN

            from datetime import datetime
            predictions = {
                "prediction_date": (datetime.now()).strftime("%Y-%m-%d"),
                "generated_at": datetime.now().isoformat(),
                "stocks": {},
                "summary": {"total_stocks": len(STOCKS_TO_TRAIN), "bullish": 0, "bearish": 0, "neutral": 0}
            }

            # No model is loaded, so there are no predictions.
            #
            # This block used to manufacture them: current_price hardcoded to
            # 100.0 for every stock, predicted_price from np.random.normal(),
            # a bullish/bearish/neutral trend derived from that random number,
            # and -- worst of all -- a "confidence" drawn from
            # np.random.uniform(0.65, 0.85). It returned {"status": "success"}.
            #
            # A reader saw ten CSE stocks with prices, directions and 65-85%
            # confidence. None of it referred to anything. Someone could have
            # traded on it.
            #
            # The stock list is still returned so the card can show which
            # symbols are covered, but with no numbers attached and a status
            # that says plainly there is nothing to show.
            for code, info in STOCKS_TO_TRAIN.items():
                predictions["stocks"][code] = {
                    "symbol": code,
                    "name": info.get("name", code),
                    "sector": info.get("sector", "Unknown"),
                    "current_price": None,
                    "predicted_price": None,
                    "expected_change_pct": None,
                    "trend": "unknown",
                    "confidence": None,
                    "is_fallback": True,
                }

            return {
                "status": "unavailable",
                "message": (
                    "The stock prediction model is not loaded, so no forecasts "
                    "are available."
                ),
                "predictions": predictions,
                "training": model_metadata.staleness("stock"),
            }
        except Exception as e:
            return {"status": "unavailable", "message": f"Stock prediction model not loaded: {e}"}

    try:
        # Try to get latest predictions from file
        predictions = predictor.get_latest_predictions()

        if predictions is None:
            # Generate fallback predictions
            logger.info("[StockAPI] No predictions found, generating fallback...")
            predictions = predictor.predict_all_stocks()
            predictions = {
                "prediction_date": (datetime.now()).strftime("%Y-%m-%d"),
                "generated_at": datetime.now().isoformat(),
                "stocks": predictions,
                "summary": {"total_stocks": len(predictions)}
            }

        return {
            "status": "success",
            "predictions": predictions,
            "training": model_metadata.staleness("stock"),
        }
    except Exception as e:
        logger.error(f"[StockAPI] Error: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/stocks/predictions/{symbol}")
async def get_stock_prediction_by_symbol(symbol: str, _user=Depends(require_user)):
    """Get prediction for a specific stock symbol."""
    predictor = get_stock_predictor()

    if predictor is None:
        return {"status": "unavailable", "message": "Stock prediction model not loaded"}

    try:
        predictions = predictor.get_latest_predictions()

        if predictions and symbol.upper() in predictions.get("stocks", {}):
            return {
                "status": "success",
                "prediction": predictions["stocks"][symbol.upper()]
            }
        else:
            # Generate fallback
            return {
                "status": "success",
                "prediction": predictor._generate_fallback_prediction(symbol.upper())
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/stocks/model/status")
async def get_stock_model_status(_user=Depends(require_user)):
    """Get stock prediction model status for all stocks."""
    remote = await model_gateway.call("stock", "/model/status")
    if remote is not None:
        return model_metadata.annotate(remote, "stock")

    from pathlib import Path
    import json

    models_dir = Path(__file__).parent.parent / "models" / "stock-price-prediction" / "artifacts" / "models"
    predictions_dir = Path(__file__).parent.parent / "models" / "stock-price-prediction" / "output" / "predictions"

    model_files = list(models_dir.glob("*_model.h5")) if models_dir.exists() else []
    prediction_files = list(predictions_dir.glob("stock_predictions_*.json")) if predictions_dir.exists() else []

    # Get training summary
    summary_path = models_dir / "training_summary.json" if models_dir.exists() else None
    training_summary = None
    if summary_path and summary_path.exists():
        with open(summary_path) as f:
            training_summary = json.load(f)

    latest_prediction = None
    if prediction_files:
        latest = max(prediction_files, key=lambda p: p.stat().st_mtime)
        latest_prediction = {
            "file": latest.name,
            "modified": datetime.fromtimestamp(latest.stat().st_mtime).isoformat()
        }

    return {
        "status": "available" if model_files else "not_trained",
        "models_trained": len(model_files),
        "trained_stocks": [f.stem.replace("_model", "").upper() for f in model_files],
        "training_summary": training_summary,
        "latest_prediction": latest_prediction,
        "predictions_available": len(prediction_files),
        "training": model_metadata.staleness("stock"),
    }


@app.get("/api/models/health")
async def get_models_health():
    """
    Topology + reachability of the four ML models.

    Each reports mode "in-process" (imported here) or "remote" (its own service),
    decided by whether {WEATHER,CURRENCY,STOCK,ANOMALY}_SERVICE_URL is set.
    Useful for confirming a Render deployment is actually wired up.
    """
    return {"status": "ok", "models": await model_gateway.health_all()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: str = None):
    # Browsers cannot set headers on `new WebSocket()`, so the bearer token
    # cannot travel the usual way. A JWT in the query string would work but ends
    # up in Render's access logs, so the client trades its token for a
    # single-use 30s ticket via POST /api/auth/ws-ticket and presents that.
    #
    # Only enforced when AUTH_ENFORCED=1; otherwise the socket stays open so the
    # existing frontend keeps working during the migration.
    if _AUTH_READY and _auth_settings is not None and _auth_settings().enforced:
        if _ws_tickets is None or _ws_tickets.redeem(ticket) is None:
            # 1008 = policy violation. Distinguishable client-side from a
            # network drop, so the UI can prompt a re-login rather than retry
            # forever against a socket that will never accept it.
            await websocket.close(code=1008)
            logger.warning("[WS] rejected connection: missing or invalid ticket")
            return

    await manager.connect(websocket)

    try:
        # Send initial state
        try:
            await websocket.send_text(json.dumps(current_state, default=str))
        except Exception as e:
            logger.debug(f"[WS] Initial send failed: {e}")
            await manager.disconnect(websocket)
            return

        # Main receive loop
        while True:
            try:
                txt = await websocket.receive_text()
            except WebSocketDisconnect:
                logger.info("[WS] Client disconnected")
                break
            except Exception as e:
                logger.debug(f"[WS] Receive error: {e}")
                break

            # Handle pong responses
            try:
                payload = json.loads(txt)
                if isinstance(payload, dict) and payload.get("type") == "pong":
                    async with manager._lock:
                        meta = manager.active_connections.get(websocket)
                        if meta is not None:
                            meta['last_pong'] = utc_now()
                            meta['misses'] = 0
                    continue
            except json.JSONDecodeError:
                continue

    finally:
        await manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    import uuid

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
