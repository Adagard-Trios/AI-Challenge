'use client'

import { ReactNode, useState } from 'react';
import { Toaster } from "./ui/toaster";
import { Toaster as Sonner } from "./ui/sonner";
import { TooltipProvider } from "./ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { RogerDataProvider } from "@/app/hooks/use-roger-data";

interface ClientWrapperProps {
  children: ReactNode;
}

export default function ClientWrapper({ children }: ClientWrapperProps) {
  const [queryClient] = useState(() => new QueryClient());

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          {/*
            One useRogerData instance for the whole app.

            Seven components called the hook, and each instance opened its own
            WebSocket and ran its own polling loop -- so a single tab held
            seven sockets, each redeeming its own single-use auth ticket, and
            fetched /api/feeds eight times on load. Mounted inside the router
            because routes are what render the consumers.
          */}
          <RogerDataProvider>
            {children}
          </RogerDataProvider>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
