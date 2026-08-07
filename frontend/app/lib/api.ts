/**
 * app/lib/api.ts
 * The single HTTP client.
 *
 * Replaces 23 raw fetch() calls across 10 components that used TWO different
 * base-URL env vars: eight read NEXT_PUBLIC_API_URL while
 * dashboard/AnomalyDetection.tsx and dashboard/StockPredictions.tsx read
 * NEXT_PUBLIC_API_BASE. Setting only one left those two panels silently talking
 * to http://localhost:8000 in production. Both are honoured here, once, so the
 * split cannot cause that again.
 *
 * Token handling:
 *   - the access token lives in a module variable, never localStorage, so an
 *     XSS cannot read it out of storage
 *   - the refresh token does live in localStorage, because it must survive a
 *     reload. It is therefore treated as compromisable: single-use, rotated on
 *     every refresh, and a replay revokes the whole family server-side
 *   - a 401 triggers one refresh-and-retry, and concurrent 401s share a single
 *     in-flight refresh rather than each spending the one-shot token
 */

const RAW_BASE =
  process.env.NEXT_PUBLIC_API_URL ||
  process.env.NEXT_PUBLIC_API_BASE ||
  "http://localhost:8000";

export const API_BASE = RAW_BASE.replace(/\/+$/, "");

const REFRESH_KEY = "roger.refresh_token";

let accessToken: string | null = null;
let refreshInFlight: Promise<boolean> | null = null;

type Listener = (authenticated: boolean) => void;
const listeners = new Set<Listener>();

export function onAuthChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function announce(authenticated: boolean) {
  listeners.forEach((fn) => {
    try {
      fn(authenticated);
    } catch {
      /* a broken listener must not break auth */
    }
  });
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null; // Safari private mode throws on localStorage access
  }
}

export function setTokens(access: string | null, refresh?: string | null) {
  accessToken = access;
  if (typeof window !== "undefined" && refresh !== undefined) {
    try {
      if (refresh) window.localStorage.setItem(REFRESH_KEY, refresh);
      else window.localStorage.removeItem(REFRESH_KEY);
    } catch {
      /* storage unavailable; the session simply will not survive a reload */
    }
  }
  announce(Boolean(access));
}

export function clearTokens() {
  setTokens(null, null);
}

/**
 * Exchange the refresh token for a new pair.
 *
 * Concurrent callers share one in-flight promise. Without that, three panels
 * hitting 401 together would each POST the same single-use refresh token, and
 * the second and third would look like replay attacks to the server -- which
 * revokes the family and logs the user out. That is a real failure mode on a
 * dashboard that fires many parallel requests on mount.
 */
async function refreshTokens(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  const refresh = getRefreshToken();
  if (!refresh) return false;

  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) {
        clearTokens();
        return false;
      }
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false; // network failure is not a logout
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export interface ApiOptions extends RequestInit {
  /** Skip the refresh-and-retry (used by auth calls themselves). */
  noRetry?: boolean;
}

export async function apiFetch(path: string, options: ApiOptions = {}): Promise<Response> {
  const { noRetry, ...init } = options;
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;

  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res = await fetch(url, { ...init, headers });

  if (res.status === 401 && !noRetry && getRefreshToken()) {
    if (await refreshTokens()) {
      const retryHeaders = new Headers(init.headers);
      if (accessToken) retryHeaders.set("Authorization", `Bearer ${accessToken}`);
      if (init.body && !retryHeaders.has("Content-Type")) {
        retryHeaders.set("Content-Type", "application/json");
      }
      res = await fetch(url, { ...init, headers: retryHeaders });
    }
  }

  return res;
}

/** apiFetch + JSON parse + throw on non-2xx. */
export async function api<T = unknown>(path: string, options: ApiOptions = {}): Promise<T> {
  const res = await apiFetch(path, options);
  const text = await res.text();

  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    const detail =
      (body as { detail?: string })?.detail ||
      (typeof body === "string" ? body : "") ||
      res.statusText;
    throw new ApiError(res.status, detail, body);
  }
  return body as T;
}

/**
 * Never-throwing GET.
 *
 * Most dashboard panels want "show data or show nothing" rather than an error
 * boundary -- one unavailable endpoint should not blank the whole dashboard.
 */
export async function apiGet<T>(path: string, fallback: T): Promise<T> {
  try {
    return await api<T>(path);
  } catch {
    return fallback;
  }
}

// --- auth ------------------------------------------------------------------

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const data = await api<{ access_token: string; refresh_token: string; user: AuthUser }>(
    "/api/auth/login",
    { method: "POST", body: JSON.stringify({ email, password }), noRetry: true },
  );
  setTokens(data.access_token, data.refresh_token);
  return data.user;
}

/**
 * Create an account and sign straight in.
 *
 * Self-registered accounts are always `viewer`, never admin. That is not a
 * detail: the social credential vault is machine-global, so an admin account
 * reaches the owner's connected Instagram. The server enforces it; this is
 * only the client half.
 */
export async function register(
  email: string,
  password: string,
  displayName?: string,
): Promise<AuthUser> {
  const data = await api<{ access_token: string; refresh_token: string; user: AuthUser }>(
    "/api/auth/register",
    {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName || null }),
      noRetry: true,
    },
  );
  setTokens(data.access_token, data.refresh_token);
  return data.user;
}

/** Whether this instance accepts sign-ups, so the form can be hidden if not. */
export async function registrationOpen(): Promise<boolean> {
  const data = await apiGet<{ open: boolean }>("/api/auth/registration", { open: false });
  return Boolean(data.open);
}

export async function logout(): Promise<void> {
  const refresh = getRefreshToken();
  try {
    if (refresh) {
      await apiFetch("/api/auth/logout", {
        method: "POST",
        body: JSON.stringify({ refresh_token: refresh }),
        noRetry: true,
      });
    }
  } finally {
    // Always clear locally, even if the server call failed -- the user asked to
    // log out and the UI must reflect that.
    clearTokens();
  }
}

export async function fetchMe(): Promise<{ authenticated: boolean; user?: AuthUser }> {
  return api("/api/me");
}

/** Restore a session from the persisted refresh token on app start. */
export async function restoreSession(): Promise<AuthUser | null> {
  if (!getRefreshToken()) return null;
  if (!(await refreshTokens())) return null;
  try {
    const me = await fetchMe();
    return me.authenticated ? me.user ?? null : null;
  } catch {
    return null;
  }
}

/**
 * WebSocket URL, with a single-use ticket when auth is on.
 *
 * Browsers cannot set headers on `new WebSocket()`, and putting the JWT in the
 * query string would write a live credential into the server's access logs.
 */
export async function websocketUrl(): Promise<string> {
  const base = `${API_BASE.replace(/^http/, "ws")}/ws`;
  if (!accessToken) return base;
  try {
    const { ticket } = await api<{ ticket: string | null }>("/api/auth/ws-ticket", {
      method: "POST",
    });
    return ticket ? `${base}?ticket=${encodeURIComponent(ticket)}` : base;
  } catch {
    return base;
  }
}
