"use client";

/**
 * app/lib/auth-context.tsx
 * Auth state for the app.
 *
 * Deliberately tolerant of AUTH_ENFORCED=0: when the backend is not enforcing
 * auth, `me` reports authenticated:false but every route still works, so the UI
 * must render the dashboard rather than a login wall. That is what lets the
 * frontend ship before the cutover.
 */

import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";

import {
  AuthUser, fetchMe, login as apiLogin, logout as apiLogout,
  onAuthChange, restoreSession,
} from "./api";

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  /** True when the backend requires auth. False => open mode, render anyway. */
  enforced: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [enforced, setEnforced] = useState(false);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        // Ask first: this tells us whether a login wall is even warranted.
        const me = await fetchMe();
        if (cancelled) return;

        setEnforced(Boolean((me as { auth_enforced?: boolean }).auth_enforced));

        if (me.authenticated && me.user) {
          setUser(me.user);
        } else {
          const restored = await restoreSession();
          if (!cancelled && restored) setUser(restored);
        }
      } catch {
        // Backend unreachable or still cold-starting. Not a logout.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // A refresh failure anywhere in the app clears the user here too.
  useEffect(() => onAuthChange((ok) => {
    if (!ok) setUser(null);
  }), []);

  const login = useCallback(async (email: string, password: string) => {
    setUser(await apiLogin(email, password));
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, enforced, login, logout }),
    [user, loading, enforced, login, logout],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/**
 * Gate children behind a login.
 *
 * Renders children when the backend is not enforcing auth, so turning
 * enforcement on is the only switch that changes behaviour.
 */
export function RequireAuth({
  children,
  fallback,
}: {
  children: React.ReactNode;
  fallback: React.ReactNode;
}) {
  const { user, loading, enforced } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-muted-foreground text-sm">Loading…</div>
      </div>
    );
  }
  if (!enforced || user) return <>{children}</>;
  return <>{fallback}</>;
}
