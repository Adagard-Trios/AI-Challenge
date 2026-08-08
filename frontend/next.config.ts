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

  // Emit .next/standalone — a self-contained server.js plus only the
  // node_modules actually reached at runtime.
  //
  // This is for the container image (frontend/Dockerfile) and changes nothing
  // for Render, which runs `npm start` against the ordinary build. Without it
  // the runtime image has to carry the entire node_modules tree, which is over
  // a gigabyte here.
  //
  // Note for anyone editing the Dockerfile: standalone does NOT include
  // .next/static or public/. They are copied separately, and forgetting them
  // serves HTML with no CSS or JS — which reads as a broken build rather than
  // a missing COPY.
  output: "standalone",

  /**
   * Serve the app shell for client-only routes.
   *
   * The app is a react-router SPA mounted at "/", so `/login` exists only once
   * the JavaScript at "/" has booted. Reaching it any other way -- a hard
   * refresh while on the login screen, a bookmark, a shared link -- asked the
   * Next server for a route it does not have, and got the bare
   * "404: This page could not be found." The build emits exactly two routes,
   * `/` and `/_not-found`, so this was reproducible every time.
   *
   * `fallback` is the right bucket rather than `beforeFiles`: it runs only
   * AFTER filesystem and dynamic routes have been checked, so a real route
   * always wins. If `/login` later becomes an actual App Router page, this
   * entry stops applying on its own rather than shadowing it.
   *
   * The browser keeps the `/login` URL; Next just serves the shell, and
   * BrowserRouter reads location.pathname and renders LoginRoute. Any future
   * client-only path needs adding here too -- which is the argument for real
   * routes eventually, not for a catch-all: a catch-all would answer 200 for
   * genuinely missing pages.
   */
  async rewrites() {
    return {
      fallback: [{ source: "/login", destination: "/" }],
    };
  },
};

export default nextConfig;
