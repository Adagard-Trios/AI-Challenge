'use client'

import { Routes, Route } from "react-router-dom";
import ClientWrapper from "./ClientWrapper";
import Index from "../pages/Index";
import Login from "../pages/Login";
import NotFound from "../pages/NotFound";
import FloatingChatBox from "./FloatingChatBox";
import { AuthProvider, RequireAuth } from "../lib/auth-context";

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
        <RequireAuth fallback={<Login />}>
          <Routes>
            <Route path="/" element={<Index />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
          <FloatingChatBox />
        </RequireAuth>
      </ClientWrapper>
    </AuthProvider>
  );
}
