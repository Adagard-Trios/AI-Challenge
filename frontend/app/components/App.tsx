'use client'

import { Routes, Route } from "react-router-dom";
import ClientWrapper from "./ClientWrapper";
import Index from "../pages/Index";
import NotFound from "../pages/NotFound";
import FloatingChatBox from "./FloatingChatBox";

export default function App() {
  return (
    <ClientWrapper>
      <Routes>
        <Route path="/" element={<Index />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      <FloatingChatBox />
    </ClientWrapper>
  );
}
