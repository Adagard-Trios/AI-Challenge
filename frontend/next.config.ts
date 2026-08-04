import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,

  // Build for a real Next server (`next start`), not a static export, so server
  // features stay available — API routes, server actions, SSR, middleware.
  //
  // Deployed on Render as a Node web service; see frontend/render.yaml.
  //
  // NOTE: NEXT_PUBLIC_* values are inlined into the client bundle at BUILD time
  // regardless of hosting model, so changing the API URL needs a rebuild rather
  // than just a restart.
};

export default nextConfig;
