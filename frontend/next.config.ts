import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactCompiler: true,

  turbopack: {
    // Pin the workspace root to this folder.
    //
    // The repo root has a stray package.json/package-lock.json (a leftover
    // `npm i @svg-maps/sri-lanka` — the package is already a real dependency
    // here). Next sees two lockfiles, infers the repo root as the workspace,
    // and warns. Left unpinned it resolves modules from the wrong directory.
    root: path.resolve(__dirname),
  },

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
