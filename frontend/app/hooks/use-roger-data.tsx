/**
 * frontend/app/hooks/use-roger-data.ts
 * Real-time data hook for Roger platform
 * 
 * FIXED: State now MERGES instead of REPLACES when receiving WebSocket updates.
 * This prevents data from disappearing when partial updates arrive.
 */
import { useState, useEffect, useCallback, useRef, createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { API_BASE, apiFetch, websocketUrl } from "@/app/lib/api";

// Reconnect backoff.
//
// This used to be a flat 1000ms with no growth and no ceiling, so a backend
// that was down got one connection attempt per second forever. A Render free
// instance takes ~50s to cold-start, which meant ~50 failed attempts (and, with
// auth on, ~50 redeemed single-use WebSocket tickets) before it could answer --
// the client hammering the server it is waiting for.
//
// Exponential with full jitter: 1s, 2s, 4s ... capped at 30s, each actual delay
// drawn uniformly from [0, computed]. The jitter matters when a server restarts
// and every open tab reconnects at once; without it they retry in lockstep and
// arrive as a thundering herd.
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const MAX_LOADING_TIME = 120000; // 2 minutes max loading time
const INITIAL_FETCH_DELAY = 1000; // Fetch from REST after 1s if no WS data
const FALLBACK_POLL_INTERVAL = 5000; // Poll REST every 5s when WS disconnected

/** Full-jitter exponential backoff: uniform draw from [0, base * 2^attempt]. */
function reconnectDelay(attempt: number): number {
  const ceiling = Math.min(
    RECONNECT_MAX_DELAY,
    RECONNECT_BASE_DELAY * 2 ** Math.min(attempt, 10),
  );
  return Math.random() * ceiling;
}

// A real-world thing an event is about, canonicalised through the taxonomy so
// that five spellings of "Colombo Port" join to one exposure entry.
export interface EventEntity {
  type: 'PLACE' | 'ORG' | 'SECTOR' | 'INFRASTRUCTURE' | 'LANE' | string;
  name: string;
  role?: 'affected' | 'actor' | 'mentioned' | string;
}

export interface RogerEvent {
  event_id: string;
  domain: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  impact_type: 'risk' | 'opportunity';
  summary: string;
  confidence: number;
  timestamp: string;
  category?: string;  // For flood_monitoring, flood_alert, etc.
  region?: 'sri_lanka' | 'world';  // NEW: for sidebar filtering
  // 0-1, higher = more likely fake. null when the LLM filter could not judge
  // this event (rate limited, malformed reply) -- it is NOT a score of 0.
  fake_news_score?: number | null;
  // false = no model verified this event; severity is the agent's own
  // keyword-derived value. Treat these as provisional in the UI.
  llm_filtered?: boolean;
  // How much this event matters to THIS user's business, and why.
  // null means it was not scored -- no exposure profile -- which is different
  // from a score of 0 ("scored, and it does not touch you").
  relevance?: {
    score: number;
    matched_on: string[];
    matches?: Array<Record<string, string | number>>;
  } | null;
  // What the event is about, canonicalised. Empty because nothing was named is
  // different from empty because the model never ran -- entities_extracted
  // carries that distinction.
  entities?: EventEntity[];
  entities_extracted?: boolean;
}

// One contributing event behind a risk index. The aggregator collects these
// while averaging each bucket (snapshot["drivers"] in combinedAgentNode.py).
export interface IndexDriver {
  event_id: string | null;
  summary: string;
  severity: string | null;
  contribution: number;
}

export interface RiskDashboard {
  // null means NOT SCORED -- no cycle has completed, or the backend is
  // unreachable. That is a different statement from 0.0 ("scored, and it is
  // low"), and the difference is the whole point on a warning system: these
  // used to be seeded to 0, which the UI then coloured green and labelled
  // "LOW". A backend outage rendered as "everything is fine".
  logistics_friction: number | null;
  compliance_volatility: number | null;
  market_instability: number | null;
  opportunity_index: number | null;
  avg_confidence: number | null;
  high_priority_count: number;
  total_events: number;
  /** null until a cycle has actually reported one. */
  last_updated: string | null;
  // Absent on an older backend, so optional rather than defaulted -- an empty
  // driver list means "nothing contributed", which is a different statement
  // from "this backend does not send drivers".
  drivers?: {
    logistics_friction?: IndexDriver[];
    compliance_volatility?: IndexDriver[];
    market_instability?: IndexDriver[];
  };
  // Regulatory activity is a story TALLY with a scaling factor, not a
  // calibrated index. It sat beside genuinely scored metrics looking identical
  // to them, so the backend flags it and ships the raw count for the UI to
  // show instead of implying a 0.7 index.
  regulatory_activity?: number;
  regulatory_activity_is_count?: boolean;
  regulatory_story_count?: number;
}

// Mirrors GET /api/rivernet (fetch_rivernet_levels in backend). The previous
// declaration described a shape the API has never sent -- location_key, status,
// water_level, alerts[].text -- so consumers read undefined and threw.
export interface RiverData {
  unit_id?: string;
  name: string;
  region: string;
  severity: 'critical' | 'warning' | 'alert' | 'normal' | 'unknown';
  level_m: number | null;
  previous_level_m?: number | null;
  max_level_m?: number | null;
  trend?: 'rising' | 'falling' | 'steady' | 'unknown';
  alert_colour?: string | null;
  reading_time?: string | null;
  reporting: boolean;
  coordinates?: unknown;
}

export interface RiverNetData {
  rivers: RiverData[];
  // Mixes warning-level stations with ones that stopped reporting
  // (severity "no_data"); use summary.flood_alerts for the flood signal.
  alerts: Array<{
    river: string;
    region: string;
    severity: string;
    level_m: number | null;
    max_level_m?: number | null;
    trend?: string;
    message: string;
  }>;
  summary: {
    total_stations: number;
    reporting: number;
    offline: number;
    rising: number;
    alerts: number;
    flood_alerts: number;
    status: string;
    regions?: string[];
  };
  fetched_at: string;
  source: string;
  error?: string;
}

export interface RogerState {
  final_ranked_feed: RogerEvent[];
  risk_dashboard_snapshot: RiskDashboard;
  run_count: number;
  status: 'initializing' | 'operational' | 'error';
  first_run_complete?: boolean;
  last_update?: string;
}

// Nothing has been measured yet, and this says so.
//
// `last_updated` was `new Date().toISOString()` -- the empty dashboard claimed
// it had been updated at the moment the page loaded, which is the one thing it
// definitely had not been. (It was also a module-level `new Date()`, an
// impurity the React Compiler flags.)
const DEFAULT_DASHBOARD: RiskDashboard = {
  logistics_friction: null,
  compliance_volatility: null,
  market_instability: null,
  opportunity_index: null,
  avg_confidence: null,
  high_priority_count: 0,
  total_events: 0,
  last_updated: null
};

// The implementation. NOT exported directly -- see the provider below.
//
// Every call to this opens its OWN WebSocket, runs its own polling loop and
// does its own initial fetches. Seven components called it, so a single browser
// tab held seven WebSocket connections, each consuming a single-use auth
// ticket, and fetched /api/feeds eight times on load.
function useRogerDataInternal() {
  const [state, setState] = useState<RogerState>({
    final_ranked_feed: [],
    risk_dashboard_snapshot: DEFAULT_DASHBOARD,
    run_count: 0,
    status: 'initializing',
    first_run_complete: false
  });

  const [isConnected, setIsConnected] = useState(false);
  const [riverData, setRiverData] = useState<RiverNetData | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const loadingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const initialFetchDoneRef = useRef(false);
  // (lastDataTimeRef was here: never read anywhere, and `useRef(Date.now())`
  // is an impure call during render that the React Compiler flags.)

  // Fetch rivernet data
  const fetchRiverData = useCallback(async () => {
    try {
      const res = await apiFetch(`${API_BASE}/api/rivernet`);
      const data = await res.json();
      if (data && data.rivers) {
        setRiverData(data);
      }
    } catch (err) {
      console.warn('[Roger] Failed to fetch rivernet data:', err);
    }
  }, []);

  // Fetch initial data from REST API (for faster initial load)
  const fetchInitialData = useCallback(async () => {
    if (initialFetchDoneRef.current) return;

    try {
      console.log('[Roger] Fetching initial data from REST API...');
      const feedRes = await apiFetch(`${API_BASE}/api/feeds`);
      const feedData = await feedRes.json();

      if (feedData.events && feedData.events.length > 0) {
        console.log(`[Roger] Loaded ${feedData.events.length} existing feeds from database`);
        initialFetchDoneRef.current = true;

        setState(prev => ({
          ...prev,
          final_ranked_feed: feedData.events,
          status: 'operational',
          first_run_complete: true
        }));
      }
    } catch (err) {
      console.warn('[Roger] Initial fetch failed, waiting for WebSocket:', err);
    }
  }, []);

  // WebSocket connection with ping/pong handling
  useEffect(() => {
    let websocket: WebSocket;
    let reconnectTimeout: NodeJS.Timeout;
    let attempt = 0;
    let disposed = false;

    /** Schedule the next attempt, backing off further each consecutive failure. */
    const scheduleReconnect = () => {
      if (disposed) return;
      const delay = reconnectDelay(attempt);
      attempt += 1;
      console.log(`[Roger] Reconnecting in ${Math.round(delay)}ms (attempt ${attempt})`);
      reconnectTimeout = setTimeout(() => {
        void connect();
      }, delay);
    };

    // websocketUrl() attaches a single-use ticket when auth is enforced.
    // Browsers cannot set headers on `new WebSocket()`, and a JWT in the query
    // string would be written into the server's access logs -- so the client
    // trades its token for a 30s ticket instead. With auth off it returns the
    // bare URL and nothing changes.
    const connect = async () => {
      try {
        const url = await websocketUrl();
        console.log('[Roger] Connecting to WebSocket:', url);
        websocket = new WebSocket(url);

        websocket.onopen = () => {
          console.log('[Roger] WebSocket connected');
          // A successful connection resets the backoff, so a brief blip does
          // not leave the next one waiting 30s.
          attempt = 0;
          setIsConnected(true);
        };

        websocket.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);

            // CRITICAL: Respond to server ping with pong
            if (data.type === 'ping') {
              console.log('[Roger] Received ping, sending pong');
              if (websocket.readyState === WebSocket.OPEN) {
                websocket.send(JSON.stringify({ type: 'pong' }));
              }
              return;
            }

            // FIXED: MERGE state instead of replacing!
            // This preserves existing data when partial updates arrive
            setState(prev => {
              // Only update fields that are actually present and non-empty in incoming data
              const newFeed = (data.final_ranked_feed && data.final_ranked_feed.length > 0)
                ? data.final_ranked_feed
                : prev.final_ranked_feed;

              const newDashboard = data.risk_dashboard_snapshot || prev.risk_dashboard_snapshot;

              // Determine status - once operational, stay operational unless error
              let newStatus = prev.status;
              if (data.status === 'error') {
                newStatus = 'error';
              } else if (data.status === 'operational' || newFeed.length > 0) {
                newStatus = 'operational';
              }

              // Once first_run_complete is true, it stays true
              const newFirstRunComplete = prev.first_run_complete || data.first_run_complete || newFeed.length > 0;

              console.log(`[Roger] State merge: feed=${newFeed.length} events, status=${newStatus}, first_run=${newFirstRunComplete}`);

              return {
                final_ranked_feed: newFeed,
                risk_dashboard_snapshot: newDashboard,
                run_count: data.run_count ?? prev.run_count,
                status: newStatus,
                first_run_complete: newFirstRunComplete,
                last_update: data.last_update || new Date().toISOString()
              };
            });

            // If we received data with feeds, mark initial fetch as done
            if (data.final_ranked_feed && data.final_ranked_feed.length > 0) {
              initialFetchDoneRef.current = true;
            }
          } catch (err) {
            console.error('[Roger] Failed to parse message:', err);
          }
        };

        websocket.onerror = () => {
          // WebSocket error events don't contain useful info when serialized
          // Log a simple warning - reconnection will happen via onclose
          console.warn('[Roger] WebSocket connection error');
          setIsConnected(false);
        };

        websocket.onclose = () => {
          setIsConnected(false);

          // Fetch from REST so the UI is not blank while we retry.
          //
          // Guarded by initialFetchDoneRef inside fetchInitialData -- it used
          // to fire on EVERY close, so a 1s reconnect loop against a down
          // backend also produced one /api/feeds request per second on top of
          // the fallback poll. That is why /api/feeds was measured at 5/s.
          fetchInitialData();

          scheduleReconnect();
        };

        wsRef.current = websocket;
      } catch (err) {
        console.error('[Roger] Connection failed:', err);
        scheduleReconnect();
      }
    };

    void connect();

    // Fetch initial data from REST API after a short delay
    const initialFetchTimeout = setTimeout(() => {
      fetchInitialData();
    }, INITIAL_FETCH_DELAY);

    // Safety timeout: Force loading complete after MAX_LOADING_TIME
    loadingTimeoutRef.current = setTimeout(() => {
      setState(prev => {
        if (!prev.first_run_complete) {
          console.log('[Roger] Loading timeout reached, forcing operational state');
          return {
            ...prev,
            status: 'operational',
            first_run_complete: true
          };
        }
        return prev;
      });
    }, MAX_LOADING_TIME);

    return () => {
      // Set before closing: onclose fires during teardown and would otherwise
      // schedule a reconnect for a hook that is going away.
      disposed = true;
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (initialFetchTimeout) clearTimeout(initialFetchTimeout);
      if (loadingTimeoutRef.current) clearTimeout(loadingTimeoutRef.current);
      if (websocket) {
        websocket.close();
      }
    };
  }, [fetchInitialData]);

  // `isConnected` read through a ref so that fetchData below can have a STABLE
  // identity.
  //
  // It previously closed over isConnected directly, so useCallback rebuilt it
  // whenever that changed -- and the polling effect depends on fetchData, so
  // every rebuild tore down the interval, started a new one, AND fired an
  // immediate fetch. Measured with the backend down that produced ~34 API
  // calls per 10s against a 5s interval that should produce 4.
  const isConnectedRef = useRef(isConnected);
  isConnectedRef.current = isConnected;

  // REST API fallback polling (when WebSocket disconnected)
  const fetchData = useCallback(async () => {
    if (isConnectedRef.current) return; // Don't fetch if WebSocket is active

    // Nobody is looking. A backgrounded tab polling a warning dashboard
    // forever is pure cost -- and these dashboards get left open for days.
    // The visibilitychange listener below re-fetches the moment it returns,
    // so nothing is stale by the time it is seen again.
    if (typeof document !== 'undefined' && document.hidden) return;

    try {
      const [dashboardRes, feedRes] = await Promise.all([
        apiFetch(`${API_BASE}/api/dashboard`),
        apiFetch(`${API_BASE}/api/feeds`)
      ]);

      const dashboard = await dashboardRes.json();
      const feed = await feedRes.json();

      setState(prev => ({
        ...prev,
        risk_dashboard_snapshot: dashboard || prev.risk_dashboard_snapshot,
        final_ranked_feed: (feed.events && feed.events.length > 0) ? feed.events : prev.final_ranked_feed,
        status: (feed.events && feed.events.length > 0) ? 'operational' : prev.status,
        first_run_complete: prev.first_run_complete || (feed.events && feed.events.length > 0)
      }));
    } catch (err) {
      console.error('[Roger] REST API fetch failed:', err);
    }
  }, []);

  // Fallback polling if WebSocket fails.
  //
  // Depends on isConnected alone -- fetchData is now identity-stable, so this
  // runs once per real connect/disconnect transition rather than once per
  // render.
  useEffect(() => {
    if (isConnected) return;

    console.log('[Roger] WebSocket disconnected - starting REST fallback polling');
    const interval = setInterval(fetchData, FALLBACK_POLL_INTERVAL);
    fetchData(); // Initial fetch immediately

    // Catch up immediately on return to the tab, rather than waiting out the
    // interval that was skipped while hidden.
    const onVisible = () => { if (!document.hidden) void fetchData(); };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      clearInterval(interval);
    };
  }, [isConnected, fetchData]);

  // Fetch rivernet data periodically
  useEffect(() => {
    fetchRiverData();
    const interval = setInterval(fetchRiverData, 60000); // Every 60s
    return () => clearInterval(interval);
  }, [fetchRiverData]);

  // ============================================
  // SITUATIONAL AWARENESS DATA (NEW)
  // ============================================
  const [powerData, setPowerData] = useState<Record<string, unknown> | null>(null);
  const [fuelData, setFuelData] = useState<Record<string, unknown> | null>(null);
  const [economyData, setEconomyData] = useState<Record<string, unknown> | null>(null);
  const [healthData, setHealthData] = useState<Record<string, unknown> | null>(null);
  const [commodityData, setCommodityData] = useState<Record<string, unknown> | null>(null);
  const [waterData, setWaterData] = useState<Record<string, unknown> | null>(null);

  // Fetch situational awareness data
  const fetchSituationalData = useCallback(async () => {
    try {
      const [powerRes, fuelRes, economyRes, healthRes, commodityRes, waterRes] = await Promise.all([
        apiFetch(`${API_BASE}/api/power`).catch(() => null),
        apiFetch(`${API_BASE}/api/fuel`).catch(() => null),
        apiFetch(`${API_BASE}/api/economy`).catch(() => null),
        apiFetch(`${API_BASE}/api/health`).catch(() => null),
        apiFetch(`${API_BASE}/api/commodities`).catch(() => null),
        apiFetch(`${API_BASE}/api/water`).catch(() => null),
      ]);

      if (powerRes?.ok) setPowerData(await powerRes.json());
      if (fuelRes?.ok) setFuelData(await fuelRes.json());
      if (economyRes?.ok) setEconomyData(await economyRes.json());
      if (healthRes?.ok) setHealthData(await healthRes.json());
      if (commodityRes?.ok) setCommodityData(await commodityRes.json());
      if (waterRes?.ok) setWaterData(await waterRes.json());
    } catch (err) {
      console.warn('[Roger] Failed to fetch situational data:', err);
    }
  }, []);

  // Fetch situational data periodically (every 5 minutes)
  useEffect(() => {
    fetchSituationalData();
    const interval = setInterval(fetchSituationalData, 300000); // Every 5 min
    return () => clearInterval(interval);
  }, [fetchSituationalData]);

  return {
    ...state,
    isConnected,
    events: state.final_ranked_feed,
    dashboard: state.risk_dashboard_snapshot,
    riverData,
    // NEW: Situational awareness data
    powerData,
    fuelData,
    economyData,
    healthData,
    commodityData,
    waterData,
  };
}

// ---------------------------------------------------------------------------
// One instance, shared.
//
// WHY A CONTEXT AND NOT REACT-QUERY
//
// react-query is already installed and its provider already mounted, and the
// obvious fix was to route these fetches through it. That would have
// deduplicated the HTTP requests and left the real problem untouched: the
// duplication here is not repeated REQUESTS, it is repeated HOOK INSTANCES.
// Each one opens its own WebSocket and runs its own polling loop, and no HTTP
// cache dedupes a socket.
//
// Seven components called useRogerData, so one browser tab held seven
// WebSocket connections -- each redeeming its own single-use auth ticket --
// alongside seven polling loops and eight fetches of /api/feeds on load.
//
// Sharing one instance fixes all of it at once and changes no component.
// ---------------------------------------------------------------------------

type RogerData = ReturnType<typeof useRogerDataInternal>;

const RogerDataContext = createContext<RogerData | null>(null);

export function RogerDataProvider({ children }: { children: ReactNode }) {
  const value = useRogerDataInternal();
  return (
    <RogerDataContext.Provider value={value}>
      {children}
    </RogerDataContext.Provider>
  );
}

/**
 * The live platform data.
 *
 * Falls back to its own instance when no provider is mounted rather than
 * throwing. A missing provider would otherwise take the whole dashboard down,
 * and the degraded behaviour -- an extra socket -- is exactly what every
 * component did before this existed.
 */
export function useRogerData(): RogerData {
  const shared = useContext(RogerDataContext);
  if (shared) return shared;
  // eslint-disable-next-line react-hooks/rules-of-hooks
  return useRogerDataInternal();
}
