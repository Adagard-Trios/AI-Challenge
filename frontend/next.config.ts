import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,

  // Emit a plain static bundle to out/ instead of running a Next server.
  //
  // Safe here because the app is already 100% client-rendered: app/page.tsx is
  // 'use client' and dynamic-imports the whole tree with { ssr: false }, so
  // nothing was being server-rendered anyway. No API routes, no middleware, and
  // no next/image (only next/font, which self-hosts at build time).
  //
  // This is what lets the frontend run as a Render Static Site — free, with no
  // spin-down and no 512 MB runtime ceiling, unlike a Node web service.
  //
  // NOTE: NEXT_PUBLIC_* values are inlined into the bundle at BUILD time, so
  // changing the API URL needs a rebuild, not just a restart.
  output: "export",
};

export default nextConfig;
