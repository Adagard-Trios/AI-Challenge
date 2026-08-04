/**
 * frontend/app/hooks/use-roger-data.ts
 * Real-time data hook for Roger platform
 * 
 * FIXED: State now MERGES instead of REPLACES when receiving WebSocket updates.
 * This prevents data from disappearing when partial updates arrive.
 */
import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const WS_URL = API_BASE.replace('http', 'ws') + '/ws';

// Timeouts for resilient connection
const RECONNECT_DELAY = 1000;  // Reduced from 3s to 1s for faster recovery
const MAX_LOADING_TIME = 120000; // 2 minutes max loading time
const INITIAL_FETCH_DELAY = 1000; // Fetch from REST after 1s if no WS data
const FALLBACK_POLL_INTERVAL = 2000; // Poll REST every 2s when WS disconnected

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
  fake_news_score?: number;  // NEW: 0-1, higher = more likely fake
}

export interface RiskDashboard {
  logistics_friction: number;
  compliance_volatility: number;
  market_instability: number;
  opportunity_index: number;
  avg_confidence: number;
  high_priority_count: number;
  total_events: number;
  last_updated: string;
}

export interface RiverData {
  location_key: string;
  name: string;
  region: string;
  status: 'danger' | 'warning' | 'rising' | 'normal' | 'unknown' | 'error';
  water_level?: { value: number; unit: string };
  url?: string;
}

export interface RiverNetData {
  rivers: RiverData[];
  alerts: Array<{ text: string; severity: string; source: string }>;
  summary: {
    total_monitored: number;
    overall_status: string;
    has_alerts: boolean;
    status_breakdown?: Record<string, number>;
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

const DEFAULT_DASHBOARD: RiskDashboard = {
  logistics_friction: 0,
  compliance_volatility: 0,
  market_instability: 0,
  opportunity_index: 0,
  avg_confidence: 0,
  high_priority_count: 0,
  total_events: 0,
  last_updated: new Date().toISOString()
};

export function useRogerData() {
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
  const lastDataTimeRef = useRef<number>(Date.now()); // Track when we last got data

  // Fetch rivernet data
  const fetchRiverData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/rivernet`);
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
      const feedRes = await fetch(`${API_BASE}/api/feeds`);
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

    const connect = () => {
      try {
        console.log('[Roger] Connecting to WebSocket:', WS_URL);
        websocket = new WebSocket(WS_URL);

        websocket.onopen = () => {
          console.log('[Roger] WebSocket connected');
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
          console.log('[Roger] WebSocket disconnected. Reconnecting in 1s...');
          setIsConnected(false);

          // IMMEDIATELY fetch from REST to prevent blank UI
          fetchInitialData();

          // Reconnect after delay
          reconnectTimeout = setTimeout(() => {
            connect();
          }, RECONNECT_DELAY);
        };

        wsRef.current = websocket;
      } catch (err) {
        console.error('[Roger] Connection failed:', err);
        reconnectTimeout = setTimeout(() => {
          connect();
        }, RECONNECT_DELAY);
      }
    };

    connect();

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
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
      if (initialFetchTimeout) clearTimeout(initialFetchTimeout);
      if (loadingTimeoutRef.current) clearTimeout(loadingTimeoutRef.current);
      if (websocket) {
        websocket.close();
      }
    };
  }, [fetchInitialData]);

  // REST API fallback polling (when WebSocket disconnected)
  const fetchData = useCallback(async () => {
    if (isConnected) return; // Don't fetch if WebSocket is active

    try {
      const [dashboardRes, feedRes] = await Promise.all([
        fetch(`${API_BASE}/api/dashboard`),
        fetch(`${API_BASE}/api/feeds`)
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
  }, [isConnected]);

  // Fallback polling if WebSocket fails - more aggressive when disconnected
  useEffect(() => {
    if (isConnected) return;

    console.log('[Roger] WebSocket disconnected - starting aggressive REST polling');
    const interval = setInterval(fetchData, FALLBACK_POLL_INTERVAL);
    fetchData(); // Initial fetch immediately

    return () => clearInterval(interval);
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
        fetch(`${API_BASE}/api/power`).catch(() => null),
        fetch(`${API_BASE}/api/fuel`).catch(() => null),
        fetch(`${API_BASE}/api/economy`).catch(() => null),
        fetch(`${API_BASE}/api/health`).catch(() => null),
        fetch(`${API_BASE}/api/commodities`).catch(() => null),
        fetch(`${API_BASE}/api/water`).catch(() => null),
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
