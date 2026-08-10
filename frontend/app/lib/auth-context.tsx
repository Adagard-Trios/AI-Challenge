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
  register as apiRegister,
  onAuthChange, restoreSession,
} from "./api";

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  /** True when the backend requires auth. False => open mode, render anyway. */
  enforced: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName?: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  // Starts TRUE: assume the wall is up until the server says otherwise.
  //
  // This was `false`, and /api/me answers 401 (not 200) to a signed-out visitor
  // whenever enforcement is on -- so the fetch below threw, the catch left this
  // at its default, and RequireAuth handed the whole dashboard to anyone who
  // opened the URL. Guessing "open" when the answer is unknown is the wrong
  // way round for an access check.
  const [enforced, setEnforced] = useState(true);

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
        // Backend unreachable, cold-starting, or refusing us. Not a logout --
        // and specifically not proof of being signed out, so still try the
        // stored refresh token. Without this a returning user with a perfectly
        // good session was sent back to the login form, because /api/me answers
        // 401 before the refresh is ever attempted.
        try {
          const restored = await restoreSession();
          if (!cancelled && restored) setUser(restored);
        } catch {
          // Genuinely nothing to restore.
        }
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

  const register = useCallback(
    async (email: string, password: string, displayName?: string) => {
      setUser(await apiRegister(email, password, displayName));
    },
    [],
  );

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, enforced, login, register, logout }),
    [user, loading, enforced, login, register, logout],
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
