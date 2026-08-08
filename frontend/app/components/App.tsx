'use client'

import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import ClientWrapper from "./ClientWrapper";
import Index from "../pages/Index";
import Login from "../pages/Login";
import NotFound from "../pages/NotFound";
import FloatingChatBox from "./FloatingChatBox";
import { AuthProvider, RequireAuth, useAuth } from "../lib/auth-context";

/**
 * The login screen, plus somewhere to go once it succeeds.
 *
 * As a bare route this was a dead end: signing in returned 200 and the page
 * stayed exactly where it was, because /login renders Login unconditionally.
 * It only ever worked as RequireAuth's fallback, where success meant the
 * fallback simply stopped being rendered.
 */
function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Navigate to="/" replace /> : <Login />;
}

/**
 * The chat, but only where the dashboard is.
 *
 * Mirrors RequireAuth's rule rather than restating it: visible when the backend
 * is not enforcing auth (open mode, dashboard renders for everyone) or when
 * there is a signed-in user. Hidden on the login screen either way.
 */
function ChatWhereItBelongs() {
  const { user, loading, enforced } = useAuth();
  const { pathname } = useLocation();

  if (loading || pathname === "/login") return null;
  if (enforced && !user) return null;
  return <FloatingChatBox />;
}

export default function App() {
  return (
    <AuthProvider>
      <ClientWrapper>
        {/*
          RequireAuth renders its children whenever the backend is NOT enforcing
          auth, so AUTH_ENFORCED is the only switch that changes behaviour. That
          is what lets this merge before the cutover rather than gating the
          dashboard the moment it ships.
        */}
        <Routes>
          {/*
            /login is reachable whether or not auth is enforced.

            It used to exist ONLY as RequireAuth's fallback, which meant that
            with AUTH_ENFORCED=0 -- the default, and how this runs locally --
            the dashboard rendered immediately and the login screen was
            unreachable. There was no sign-in control anywhere. That made the
            social account fields impossible to get to: they require a user by
            design (they store a password), so they showed "sign in to manage
            social accounts" next to no way of doing it.
          */}
          <Route path="/login" element={<LoginRoute />} />
          <Route
            path="/"
            element={
              <RequireAuth fallback={<Login />}>
                <Index />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
        {/*
          The assistant belongs to the dashboard, not to every screen.

          Mounted here unconditionally it also rendered on /login and on the
          404 page -- so an unauthenticated visitor got a "Roger" button that
          posts to /api/rag/chat with no token. Gated on the same condition
          RequireAuth uses, so it appears exactly where the dashboard does.
        */}
        <ChatWhereItBelongs />
      </ClientWrapper>
    </AuthProvider>
  );
}
