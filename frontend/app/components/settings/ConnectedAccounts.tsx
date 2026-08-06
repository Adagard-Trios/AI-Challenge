"use client";

/**
 * ConnectedAccounts.tsx
 * Connect social accounts, and see the state of each one.
 *
 * The connect flow is deliberately honest about two things that most tools
 * bury:
 *   1. Connecting requires a desktop, once per platform. Every platform's auth
 *      cookie is httpOnly, so no browser-side trick can capture a session --
 *      a phone genuinely cannot do this, and saying so beats a flow that fails.
 *   2. Automated collection is against every platform's terms. The user is told
 *      before they connect, not after their account is restricted.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Clock, Copy, Loader2, Monitor,
  Plug, RefreshCw, ShieldCheck, Trash2, XCircle,
} from "lucide-react";

import { API_BASE, api, apiGet } from "@/app/lib/api";

interface Connection {
  platform: string;
  handle: string | null;
  status: "ok" | "expired" | "challenged" | "disconnected";
  status_reason: string | null;
  session_expires_at: string | null;
  days_until_expiry: number | null;
  last_collected_at: string | null;
  posts_collected: number;
  cooldown_until: string | null;
  // Today's pacing consumption, as last reported by the connector. null means
  // "not reported" — which is NOT the same as "nothing spent", so it must never
  // be rendered as 0.
  budget: {
    day: string;
    requests_used: number;
    requests_cap: number;
    posts_used: number;
    posts_cap: number;
    requests_remaining: number;
    fraction_used: number | null;
    exhausted: boolean;
  } | null;
}

/**
 * How much of today's collection budget this account has spent.
 *
 * scrapers/hygiene.py caps each platform per UTC day — 120 requests for
 * X/Twitter, 60 for Facebook and Instagram, 40 for LinkedIn — and those caps
 * are the main thing standing between a personal account and a restriction.
 * They were enforced silently. A user near a cap saw collection return fewer
 * posts and then stop, with the reason only in a local log, so "why did it stop
 * collecting?" had no answer in the interface.
 *
 * Showing consumption is what lets someone act *before* a restriction lands
 * rather than after — pause collection, spread it out, or leave it alone.
 */
const BudgetBar = ({ budget }: { budget: Connection["budget"] }) => {
  if (!budget || !budget.requests_cap) return null;

  const fraction = Math.max(0, Math.min(1, budget.fraction_used ?? 0));
  const tone =
    fraction >= 0.9
      ? "bg-red-400"
      : fraction >= 0.7
        ? "bg-amber-400"
        : "bg-emerald-400";

  return (
    <div className="mt-1.5 max-w-xs">
      <div className="flex items-center justify-between text-xs text-slate-400 mb-0.5">
        <span title="Requests this account has made today, against its daily cap">
          Today&apos;s collection budget
        </span>
        <span className="font-mono">
          {budget.requests_used}/{budget.requests_cap}
        </span>
      </div>
      <div className="h-1 w-full rounded-full bg-slate-700 overflow-hidden">
        <div
          className={`h-full ${tone} transition-all duration-500`}
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      {budget.exhausted ? (
        <p className="mt-1 text-xs text-amber-300/90">
          Daily cap reached. Collection pauses until midnight UTC — this is the
          pacing working, not a fault.
        </p>
      ) : fraction >= 0.7 ? (
        <p className="mt-1 text-xs text-amber-300/90">
          {budget.requests_remaining} requests left today.
        </p>
      ) : null}
    </div>
  );
};

const PLATFORMS = ["twitter", "linkedin", "facebook", "instagram"] as const;

const LABELS: Record<string, string> = {
  twitter: "X (Twitter)",
  linkedin: "LinkedIn",
  facebook: "Facebook",
  instagram: "Instagram",
};

function StatusBadge({ conn }: { conn: Connection }) {
  const map = {
    ok: { icon: CheckCircle2, cls: "text-emerald-400", label: "Connected" },
    expired: { icon: Clock, cls: "text-amber-400", label: "Session expired" },
    challenged: { icon: AlertTriangle, cls: "text-red-400", label: "Paused by platform" },
    disconnected: { icon: XCircle, cls: "text-slate-500", label: "Disconnected" },
  }[conn.status] ?? { icon: XCircle, cls: "text-slate-500", label: conn.status };

  const Icon = map.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${map.cls}`}>
      <Icon className="h-3.5 w-3.5" />
      {map.label}
    </span>
  );
}

export default function ConnectedAccounts() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [pairCode, setPairCode] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectorRunning, setConnectorRunning] = useState<boolean | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await apiGet<{ connections: Connection[] }>(
      "/api/connections",
      { connections: [] },
    );
    setConnections(data.connections ?? []);

    // Whether a connector is actually polling. Without this the buttons below
    // would queue work that nothing picks up, with no explanation -- a button
    // that appears to work and silently does nothing.
    const cmds = await apiGet<{ connector_running: boolean }>(
      "/api/connector/commands",
      { connector_running: false },
    );
    setConnectorRunning(cmds.connector_running ?? false);

    setLoading(false);
  }, []);

  const send = async (action: string, platform: string) => {
    setBusy(platform);
    setError(null);
    setNotice(null);
    try {
      const res = await api<{ message: string; connector_running: boolean }>(
        "/api/connector/commands",
        {
          method: "POST",
          body: JSON.stringify({ action, platform }),
          headers: { "Content-Type": "application/json" },
        },
      );
      setNotice(res.message);
      setConnectorRunning(res.connector_running);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not ${action} ${platform}`);
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    void load();
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [load]);

  const startPairing = async () => {
    setError(null);
    setBusy("pair");
    try {
      const res = await api<{ pair_code: string }>("/api/connector/pair", { method: "POST" });
      setPairCode(res.pair_code);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start pairing");
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async (platform: string) => {
    setBusy(platform);
    try {
      await api(`/api/connections/${platform}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not disconnect");
    } finally {
      setBusy(null);
    }
  };

  const resume = async (platform: string) => {
    setBusy(platform);
    try {
      await api(`/api/connections/${platform}/resume`, { method: "POST" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not resume");
    } finally {
      setBusy(null);
    }
  };

  const byPlatform = new Map(connections.map((c) => [c.platform, c]));

  return (
    <div className="space-y-6">
      {/* What this does with credentials, stated before anything is connected. */}
      <div className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 p-4">
        <div className="flex gap-3">
          <ShieldCheck className="h-5 w-5 shrink-0 text-emerald-400" />
          <div className="space-y-1 text-sm">
            <p className="font-medium text-emerald-200">
              Your session cookies never reach this server.
            </p>
            <p className="text-emerald-100/70">
              Accounts are connected on your own computer, by the connector app.
              Collection runs there too, from your own network. This server
              receives the posts that were collected and the status of each
              account &mdash; never a credential. There is nowhere here to store one.
            </p>
          </div>
        </div>
      </div>

      {/* The part most tools omit. */}
      <div className="rounded-lg border border-amber-800/40 bg-amber-950/20 p-4">
        <div className="flex gap-3">
          <AlertTriangle className="h-5 w-5 shrink-0 text-amber-400" />
          <div className="space-y-1 text-sm">
            <p className="font-medium text-amber-200">Before you connect an account</p>
            <p className="text-amber-100/70">
              Automated collection is against the terms of service of X,
              LinkedIn, Facebook and Instagram, regardless of how the session was
              obtained. Accounts can be restricted or banned. Collecting from
              your own network lowers that risk; it does not remove it. Consider
              using an account you can afford to lose.
            </p>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-800/40 bg-red-950/20 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {notice && (
        <div className="rounded-lg border border-sky-800/40 bg-sky-950/20 p-3 text-sm text-sky-200">
          {notice}
        </div>
      )}

      {/* Whether the buttons below will actually do anything.
          The connector is what executes them, on the user's own machine. If it
          is not running, a click queues work that nothing picks up -- so say so
          before they click, not after nothing happens. */}
      {connectorRunning === false && (
        <div className="rounded-lg border border-amber-800/40 bg-amber-950/20 p-3 text-sm">
          <p className="font-medium text-amber-200">Your connector is not running.</p>
          <p className="mt-1 text-amber-100/70">
            The buttons below queue work for it and it will pick them up within
            a minute of starting. On your computer:
          </p>
          <code className="mt-2 block rounded bg-slate-900/60 px-2 py-1 font-mono text-xs text-slate-300">
            python -m connector run
          </code>
        </div>
      )}

      {/* Pairing */}
      <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            <Monitor className="h-4 w-4" /> Connector
          </h3>
          <button
            onClick={startPairing}
            disabled={busy === "pair"}
            className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-slate-600 disabled:opacity-50"
          >
            {busy === "pair" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Get pairing code"}
          </button>
        </div>

        {pairCode ? (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <code className="rounded bg-slate-900 px-4 py-2 font-mono text-xl tracking-widest text-emerald-300">
                {pairCode}
              </code>
              <button
                onClick={() => navigator.clipboard?.writeText(pairCode)}
                className="text-slate-400 hover:text-slate-200"
                aria-label="Copy pairing code"
              >
                <Copy className="h-4 w-4" />
              </button>
              <span className="text-xs text-slate-500">expires in 10 minutes</span>
            </div>
            {/* The server here is the BACKEND, which on Render is a different
                host from this page. The previous version built it from
                window.location.origin with a regex that matched the whole
                origin and replaced it with "" -- so the `||` fallback always
                fired and every user was shown the literal placeholder
                <backend-url>, which is unusable. API_BASE is the value that is
                actually correct and it is already configured. */}
            <div className="space-y-2 rounded bg-slate-900/60 p-3 font-mono text-xs text-slate-300">
              <div>
                <div className="mb-1 font-sans text-slate-500">
                  1. Pair this computer:
                </div>
                <div className="break-all">
                  python -m connector pair {pairCode} --server {API_BASE}
                </div>
              </div>
              <div>
                <div className="mb-1 font-sans text-slate-500">
                  2. Save a login (stays on your computer, encrypted):
                </div>
                <div className="break-all">
                  python -m connector credentials set linkedin
                </div>
              </div>
              <div>
                <div className="mb-1 font-sans text-slate-500">
                  3. Sign in — opens your browser, you complete any 2FA:
                </div>
                <div className="break-all">
                  python -m connector connect linkedin
                </div>
              </div>
            </div>
            <p className="text-xs text-slate-400">
              Step 2 is optional and only pre-fills the login form. Your password
              is encrypted on your own machine and is never sent here — this
              server has no endpoint that accepts one.
            </p>
          </div>
        ) : (
          <p className="text-xs text-slate-400">
            The connector runs on your computer and does the collecting. Pair it
            once, then connect your accounts there. Passwords and session cookies
            stay on your machine.
          </p>
        )}
      </div>

      {/* Accounts */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-slate-200">Accounts</h3>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading…
          </div>
        ) : (
          PLATFORMS.map((platform) => {
            const conn = byPlatform.get(platform);
            return (
              <div
                key={platform}
                className="flex items-center justify-between rounded-lg border border-slate-700/50 bg-slate-800/40 p-4"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium text-slate-100">
                      {LABELS[platform]}
                    </span>
                    {conn ? <StatusBadge conn={conn} /> : (
                      <span className="text-xs text-slate-500">Not connected</span>
                    )}
                  </div>

                  {conn && (
                    <div className="text-xs text-slate-400">
                      {conn.handle && <span className="mr-3">{conn.handle}</span>}
                      {conn.days_until_expiry !== null && (
                        <span className={`mr-3 ${conn.days_until_expiry <= 7 ? "text-amber-400" : ""}`}>
                          expires in {conn.days_until_expiry}d
                        </span>
                      )}
                      <span>{conn.posts_collected} posts collected</span>
                    </div>
                  )}

                  {conn && <BudgetBar budget={conn.budget} />}

                  {conn?.status === "challenged" && (
                    <p className="max-w-xl text-xs text-red-300/80">
                      {LABELS[platform]} asked for a verification step, so
                      collection stopped. Open the account in a browser, complete
                      whatever it asks, then resume here. It will not retry on its
                      own &mdash; retrying into a challenge is what turns a
                      temporary block into a permanent one.
                    </p>
                  )}
                  {conn?.status === "expired" && (
                    <p className="text-xs text-amber-300/80">
                      The session expired. Reconnect below &mdash; your browser
                      will open on your own machine.
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {conn?.status === "challenged" && (
                    <button
                      onClick={() => resume(platform)}
                      disabled={busy === platform}
                      className="flex items-center gap-1.5 rounded-md bg-slate-700 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-600 disabled:opacity-50"
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> Resume
                    </button>
                  )}
                  {conn && conn.status === "ok" && (
                    <button
                      onClick={() => send("collect", platform)}
                      disabled={busy === platform}
                      className="flex items-center gap-1.5 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-50"
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> Collect now
                    </button>
                  )}

                  {/* Connect and Reconnect are the same instruction: the
                      connector opens a real browser on the user's machine and
                      pre-fills from its own local vault. Nothing about the
                      credential passes through here. */}
                  <button
                    onClick={() => send("connect", platform)}
                    disabled={busy === platform}
                    className="flex items-center gap-1.5 rounded-md bg-slate-700 px-3 py-1.5 text-xs text-slate-100 hover:bg-slate-600 disabled:opacity-50"
                  >
                    {busy === platform ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Plug className="h-3.5 w-3.5" />
                    )}
                    {conn ? "Reconnect" : "Connect"}
                  </button>

                  {conn && (
                    <button
                      onClick={() => disconnect(platform)}
                      disabled={busy === platform}
                      className="flex items-center gap-1.5 rounded-md border border-slate-600 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-700 disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Disconnect
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <p className="text-xs text-slate-500">
        Connecting an account requires a desktop or laptop, once per platform.
        Every platform stores its login in an httpOnly cookie, which no web page
        &mdash; including this one &mdash; is able to read. Everything else here
        works on a phone.
      </p>
    </div>
  );
}
