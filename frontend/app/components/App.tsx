'use client'

import { Navigate, Route, Routes } from "react-router-dom";
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
        <FloatingChatBox />
      </ClientWrapper>
    </AuthProvider>
  );
}
