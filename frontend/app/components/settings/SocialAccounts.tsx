"use client";

/**
 * SocialAccounts.tsx
 * Sign in to social accounts from the dashboard, with the fields right here.
 *
 * This replaces a terminal. Connecting used to mean running
 * `python -m connector credentials linkedin` and typing a password into a
 * prompt, because the server was a shared host and a password sent to it was a
 * password on someone else's machine.
 *
 * Hosting from your own laptop removes that: the server and "your machine" are
 * the same computer, so the password goes to localhost and the browser opens in
 * front of you.
 *
 * Two things this UI refuses to imply, because both would be false:
 *
 *   1. That saving a password logs you in. It does not — it pre-fills the
 *      platform's own form and stops. You finish the sign-in, including 2FA.
 *      Automating that step is what turns a routine device-verification prompt
 *      into a lockout.
 *   2. That connected accounts are safe from restriction. Automated collection
 *      breaches every one of these platforms' terms. The budget bar exists so
 *      you can see how hard an account is being worked and ease off before a
 *      restriction lands — not because one cannot happen.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, CheckCircle2, Download, Eye, EyeOff, KeyRound,
  Loader2, LogIn, Monitor, RefreshCw, ShieldCheck, Trash2,
} from "lucide-react";

import { ApiError, api } from "@/app/lib/api";

interface Job {
  platform: string;
  state: "starting" | "awaiting_login" | "saving" | "done" | "failed" | string;
  message: string;
  handle: string | null;
  running: boolean;
}

interface Budget {
  requests_used: number;
  requests_cap: number;
  posts_used: number;
  posts_cap: number;
  exhausted: boolean;
}

interface Account {
  platform: string;
  connected: boolean;
  handle: string | null;
  has_credentials: boolean;
  username: string | null;
  job: Job | null;
  budget: Budget | null;
  /** Set when a challenge or backoff has paused collection for this account. */
  paused: { paused: boolean; kind: string; detail: string } | null;
}

const LABELS: Record<string, string> = {
  twitter: "X (Twitter)",
  linkedin: "LinkedIn",
  facebook: "Facebook",
  instagram: "Instagram",
  reddit: "Reddit",
};

/** Daily request caps, so the bar means something before the first run. */
const BudgetBar = ({ budget }: { budget: Budget | null }) => {
  if (!budget || !budget.requests_cap) return null;

  const fraction = Math.max(
    0, Math.min(1, budget.requests_used / budget.requests_cap),
  );
  const tone =
    fraction >= 0.9 ? "bg-red-400"
      : fraction >= 0.7 ? "bg-amber-400"
        : "bg-emerald-400";

  return (
    <div className="mt-2 max-w-xs">
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
      {budget.exhausted && (
        <p className="mt-1 text-xs text-amber-300/90">
          Daily cap reached. Collection pauses until midnight UTC — the pacing
          working, not a fault.
        </p>
      )}
    </div>
  );
};

const AccountRow = ({
  account,
  onChanged,
}: {
  account: Account;
  onChanged: () => void;
}) => {
  const { platform } = account;

  const [username, setUsername] = useState(account.username ?? "");
  const [password, setPassword] = useState("");
  const [reveal, setReveal] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const job = account.job;

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    setNote(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  };

  const saveLogin = () =>
    run("save", async () => {
      await api("/api/social/credentials", {
        method: "POST",
        body: JSON.stringify({ platform, username, password }),
      });
      // Drop the password from component state the moment it is stored. It is
      // encrypted on the host machine; keeping a second copy in a React state
      // tree buys nothing and lives as long as the tab does.
      setPassword("");
      setNote("Login saved on this machine. Click Connect to finish signing in.");
    });

  const connect = () =>
    run("connect", async () => {
      await api("/api/social/connect", {
        method: "POST",
        body: JSON.stringify({ platform }),
      });
    });

  const collect = () =>
    run("collect", async () => {
      const r = await api<{ collected: number; stored: number; status: string }>(
        "/api/social/collect",
        { method: "POST", body: JSON.stringify({ platform }) },
      );
      setNote(
        r.status === "ok" || r.status === "budget_exhausted"
          ? `Collected ${r.collected} posts, stored ${r.stored} new.`
          : `Collection returned "${r.status}".`,
      );
    });

  const disconnect = () =>
    run("disconnect", async () => {
      await api("/api/social/disconnect", {
        method: "POST",
        body: JSON.stringify({ platform }),
      });
      setNote("Local session deleted. Use the platform's own "
        + "“log out of all devices” to end it there too.");
    });

  const resume = () =>
    run("resume", async () => {
      await api("/api/social/resume", {
        method: "POST",
        body: JSON.stringify({ platform }),
      });
      setNote("Collection resumed. It will retry on the next cycle.");
    });

  const forget = () =>
    run("forget", async () => {
      await api(`/api/social/credentials/${platform}`, { method: "DELETE" });
      setUsername("");
      setPassword("");
      setNote("Saved login removed from this machine.");
    });

  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2.5">
          <span className="text-sm font-medium text-slate-100">
            {LABELS[platform] ?? platform}
          </span>
          {account.connected ? (
            <span className="flex items-center gap-1 text-xs text-emerald-400">
              <CheckCircle2 className="w-3.5 h-3.5" />
              Connected{account.handle ? ` as ${account.handle}` : ""}
            </span>
          ) : (
            <span className="text-xs text-slate-500">Not connected</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {account.connected && (
            <>
              <button
                onClick={collect}
                disabled={busy !== null}
                className="flex items-center gap-1.5 rounded-md border border-slate-600 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700/50 disabled:opacity-50"
              >
                {busy === "collect"
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  : <Download className="w-3.5 h-3.5" />}
                Collect now
              </button>
              <button
                onClick={disconnect}
                disabled={busy !== null}
                className="flex items-center gap-1.5 rounded-md border border-slate-600 px-2.5 py-1.5 text-xs text-slate-400 hover:bg-slate-700/50 disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Disconnect
              </button>
            </>
          )}
        </div>
      </div>

      {/* A challenge stops this account until a person confirms they have
          checked it. Without somewhere to say that, a challenged account stays
          silently stopped forever. */}
      {account.paused && (
        <div className="mb-3 flex flex-wrap items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-2.5 text-xs text-amber-200">
          <AlertTriangle className="mt-0.5 w-3.5 h-3.5 shrink-0" />
          <span className="flex-1">
            {account.paused.kind === "challenged"
              ? `${LABELS[platform] ?? platform} asked for a verification step, so collection stopped. Open the account in a browser, complete whatever it asks, then resume here. It will not retry on its own.`
              : `Backing off after repeated failures. ${account.paused.detail}`}
          </span>
          <button
            onClick={resume}
            disabled={busy !== null}
            className="rounded-md border border-amber-400/50 px-2 py-1 text-xs text-amber-100 hover:bg-amber-500/20 disabled:opacity-50"
          >
            {busy === "resume" ? "Resuming…" : "I've checked — resume"}
          </button>
        </div>
      )}

      {/* Credential fields. Saving is separate from connecting on purpose:
          saving stores a password, connecting opens a browser, and merging them
          into one button would hide which of the two just happened. */}
      <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
        <label className="block">
          <span className="mb-1 block text-xs text-slate-400">
            Username or email
          </span>
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="off"
            placeholder={`your ${LABELS[platform] ?? platform} login`}
            className="w-full rounded-md border border-slate-600 bg-slate-900/60 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-slate-400 focus:outline-none"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-slate-400">Password</span>
          <div className="relative">
            <input
              type={reveal ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              placeholder={account.has_credentials ? "•••••••• (saved)" : "password"}
              className="w-full rounded-md border border-slate-600 bg-slate-900/60 px-2.5 py-1.5 pr-8 text-sm text-slate-100 placeholder:text-slate-600 focus:border-slate-400 focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setReveal(!reveal)}
              aria-label={reveal ? "Hide password" : "Show password"}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
            >
              {reveal ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </label>

        <div className="flex gap-2">
          <button
            onClick={saveLogin}
            disabled={busy !== null || !username.trim() || !password}
            title="Encrypt and store on this machine, for pre-filling the login form"
            className="flex items-center gap-1.5 rounded-md border border-slate-600 px-2.5 py-1.5 text-xs text-slate-200 hover:bg-slate-700/50 disabled:opacity-40"
          >
            {busy === "save"
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <KeyRound className="w-3.5 h-3.5" />}
            Save
          </button>

          <button
            onClick={connect}
            disabled={busy !== null || Boolean(job?.running)}
            className="flex items-center gap-1.5 rounded-md bg-sky-600/90 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-600 disabled:opacity-40"
          >
            {busy === "connect" || job?.running
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <LogIn className="w-3.5 h-3.5" />}
            {account.connected ? "Reconnect" : "Connect"}
          </button>
        </div>
      </div>

      {account.has_credentials && (
        <button
          onClick={forget}
          disabled={busy !== null}
          className="mt-2 text-xs text-slate-500 hover:text-slate-300 disabled:opacity-50"
        >
          Forget saved login
        </button>
      )}

      {/* Live progress during the minute or two a human spends signing in. */}
      {job && job.state !== "done" && (
        <div
          className={`mt-3 flex items-start gap-2 rounded-md p-2.5 text-xs ${
            job.state === "failed"
              ? "bg-red-500/10 text-red-300"
              : "bg-sky-500/10 text-sky-200"
          }`}
        >
          {job.running
            ? <Loader2 className="mt-0.5 w-3.5 h-3.5 shrink-0 animate-spin" />
            : <AlertTriangle className="mt-0.5 w-3.5 h-3.5 shrink-0" />}
          <span>{job.message}</span>
        </div>
      )}

      {job?.state === "done" && !note && (
        <p className="mt-3 flex items-start gap-2 text-xs text-emerald-300">
          <CheckCircle2 className="mt-0.5 w-3.5 h-3.5 shrink-0" />
          {job.message}
        </p>
      )}

      {note && <p className="mt-3 text-xs text-slate-300">{note}</p>}
      {error && (
        <p className="mt-3 flex items-start gap-2 text-xs text-red-300">
          <AlertTriangle className="mt-0.5 w-3.5 h-3.5 shrink-0" />
          {error}
        </p>
      )}

      <BudgetBar budget={account.budget} />
    </div>
  );
};

const SocialAccounts = () => {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const anyRunning = useRef(false);

  const load = useCallback(async () => {
    try {
      const data = await api<{ accounts: Account[] }>("/api/social/accounts");
      setAccounts(data.accounts ?? []);
      anyRunning.current = (data.accounts ?? []).some((a) => a.job?.running);
      setSignedOut(false);
    } catch (e) {
      // Distinguish "not signed in" from "no accounts". Swallowing the 401 into
      // an empty list is what made this panel look broken: it rendered nothing
      // and gave no reason, when the actual answer is one command away.
      setSignedOut(e instanceof ApiError && e.status === 401);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll quickly only while a login is in flight — the message counts down the
  // remaining time, and a stale one would be worse than none. Otherwise idle.
  useEffect(() => {
    const timer = setInterval(() => {
      if (anyRunning.current) void load();
    }, 2000);
    return () => clearInterval(timer);
  }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-100">
            <ShieldCheck className="w-5 h-5 text-sky-400" />
            SOCIAL ACCOUNTS
          </h2>
          <p className="mt-0.5 text-xs text-slate-400">
            Sign in once per platform. Sessions are reused afterwards, which is
            the single biggest factor in how long a connected account keeps
            working.
          </p>
        </div>
        <button
          onClick={() => void load()}
          className="flex items-center gap-1.5 rounded-md border border-slate-600 px-2.5 py-1.5 text-xs text-slate-300 hover:bg-slate-700/50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Where the browser opens is genuinely surprising if you are not sitting
          at the host machine, so it is stated before the buttons, not after. */}
      <div className="flex items-start gap-2 rounded-lg border border-slate-700/50 bg-slate-800/30 p-3 text-xs text-slate-300">
        <Monitor className="mt-0.5 w-4 h-4 shrink-0 text-slate-400" />
        <div className="space-y-1">
          <p>
            <strong className="text-slate-200">Connect</strong> opens a real
            browser window <em>on the machine running this server</em> and
            pre-fills your login. You complete the sign-in there, including any
            2FA — the password is never submitted for you.
          </p>
          <p className="text-slate-400">
            Passwords are encrypted on that machine and are never returned by
            this API. Automated collection is against every platform&apos;s
            terms; the budget bars show how hard each account is being worked so
            you can ease off before a restriction lands.
          </p>
        </div>
      </div>

      {signedOut ? (
        /* The 401 used to render as an empty list with no explanation. These
           endpoints store a password and open a browser, so they will not work
           anonymously by design -- but "why is this blank" deserves an answer
           and a command, not silence. */
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4 text-sm">
          <p className="mb-2 font-medium text-slate-200">
            Sign in to manage social accounts.
          </p>
          <p className="mb-3 text-xs text-slate-400">
            These fields store a password and open a browser on this machine, so
            they always require an account — even when auth is otherwise off.
            There is no self-registration; create the first account with:
          </p>
          <pre className="overflow-x-auto rounded bg-slate-900/70 p-2.5 text-xs text-slate-300">
            cd backend{"\n"}python scripts/create_admin.py
          </pre>
          <p className="mt-2 text-xs text-slate-500">
            That account is only for this dashboard. It is unrelated to your
            social media passwords, which are stored separately and encrypted.
          </p>
        </div>
      ) : loading && accounts.length === 0 ? (
        <p className="text-sm text-slate-400">Loading accounts…</p>
      ) : (
        <div className="space-y-3">
          {accounts.map((account) => (
            <AccountRow
              key={account.platform}
              account={account}
              onChanged={load}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export default SocialAccounts;
