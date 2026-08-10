"use client";

/**
 * Login.tsx
 *
 * Shown only when the backend reports AUTH_ENFORCED=1. While enforcement is off
 * the dashboard renders as before, which is what lets this ship ahead of the
 * cutover.
 */

import React, { useEffect, useState } from "react";
import { AlertCircle, Loader2, LogIn, UserPlus } from "lucide-react";

import { useAuth } from "@/app/lib/auth-context";
import { registrationOpen } from "@/app/lib/api";

export default function Login() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"signin" | "register">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // null = not asked yet. Starting at `false` meant the page stated "Accounts
  // are invite-only" for as long as the probe took -- several seconds against a
  // tunnelled backend -- so a visitor who read it early was told sign-ups were
  // closed when they were open. Unknown must not render as a definite no.
  const [canRegister, setCanRegister] = useState<boolean | null>(null);

  // Ask the server rather than assuming. An instance can disable sign-ups, and
  // offering a form that always 403s is worse than not offering one.
  useEffect(() => {
    let cancelled = false;
    void registrationOpen().then((open) => {
      if (!cancelled) setCanRegister(open);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const registering = mode === "register";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (registering) {
        await register(email.trim(), password, displayName.trim() || undefined);
      } else {
        await login(email.trim(), password);
      }
    } catch (err) {
      // Sign-in returns the same message for an unknown email and a wrong
      // password, so it cannot be used to enumerate accounts. Registration
      // deliberately does say "already exists" -- there, the alternative is
      // someone retyping a password they already have.
      setError(
        err instanceof Error
          ? err.message
          : registering ? "Could not create the account" : "Sign in failed",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1 text-center">
          <h1 className="text-xl font-semibold text-foreground">
            Sri Lanka AI Challenge 2026
          </h1>
          <p className="text-sm text-muted-foreground">
            {registering
              ? "Create an account to view the intelligence dashboard"
              : "Sign in to view the intelligence dashboard"}
          </p>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="email" className="text-sm font-medium text-foreground">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {registering && (
            <div className="space-y-1.5">
              <label htmlFor="displayName" className="text-sm font-medium text-foreground">
                Name <span className="text-muted-foreground">(optional)</span>
              </label>
              <input
                id="displayName"
                type="text"
                autoComplete="name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="password" className="text-sm font-medium text-foreground">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              autoComplete={registering ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/10 p-2.5 text-sm text-destructive"
            >
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <button
            type="submit"
            disabled={busy || !email || !password}
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : registering ? (
              <UserPlus className="h-4 w-4" />
            ) : (
              <LogIn className="h-4 w-4" />
            )}
            {busy
              ? registering ? "Creating account…" : "Signing in…"
              : registering ? "Create account" : "Sign in"}
          </button>
        </form>

        {canRegister === null ? (
          /* Reserve the line's height so the form does not jump when the
             answer arrives, but claim nothing while we do not know. */
          <div className="h-4" aria-hidden />
        ) : canRegister ? (
          <div className="space-y-2 text-center">
            <button
              type="button"
              onClick={() => {
                setMode(registering ? "signin" : "register");
                setError(null);
              }}
              className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              {registering
                ? "Already have an account? Sign in"
                : "No account? Create one"}
            </button>
            {registering && (
              /* Said before signing up rather than discovered afterwards. This
                 used to warn that connecting was owner-only; the vault is
                 per-user now, so the useful thing to state is the isolation. */
              <p className="text-xs text-muted-foreground">
                Your account is your own: the social accounts you connect and
                everything collected from them are visible only to you.
              </p>
            )}
          </div>
        ) : (
          <p className="text-center text-xs text-muted-foreground">
            Accounts are invite-only. Ask an administrator for an invite link.
          </p>
        )}
      </div>
    </div>
  );
}
