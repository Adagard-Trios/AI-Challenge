import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactCompiler: true,

  compiler: {
    /**
     * Strip console.log from production builds, keep console.error/warn.
     *
     * There were 25 console statements shipping, 9 of them plain logs and most
     * of those in the WebSocket lifecycle -- "[Roger] Connecting...",
     * "[Roger] State merge: feed=18 events...", one per reconnect and one per
     * message. On a dashboard left open all day that is a console nobody can
     * read and a small continuous cost, and the state-merge line prints feed
     * contents into a place we do not control.
     *
     * error and warn are excluded deliberately: they are the ones that matter
     * when someone reports "it stopped updating", and PanelBoundary relies on
     * console.error to leave the real stack behind when it swallows a crash.
     */
    removeConsole: { exclude: ["error", "warn"] },
  },

  turbopack: {
    // Pin the workspace root to this folder.
    //
    // The repo root has a stray package.json/package-lock.json (a leftover
    // `npm i @svg-maps/sri-lanka`, the package is already a real dependency
    // here). Next sees two lockfiles, infers the repo root as the workspace,
    // and warns. Left unpinned it resolves modules from the wrong directory.
    root: path.resolve(__dirname),
  },

  // Build for a real Next server (`next start`), not a static export, so server
  // features stay available, API routes, server actions, SSR, middleware.
  //
  // Deployed on Render as a Node web service; see frontend/render.yaml.
  //
  // NOTE: NEXT_PUBLIC_* values are inlined into the client bundle at BUILD time
  // regardless of hosting model, so changing the API URL needs a rebuild rather
  // than just a restart.

  // Emit .next/standalone, a self-contained server.js plus only the
  // node_modules actually reached at runtime.
  //
  // This is for the container image (frontend/Dockerfile) and changes nothing
  // for Render, which runs `npm start` against the ordinary build. Without it
  // the runtime image has to carry the entire node_modules tree, which is over
  // a gigabyte here.
  //
  // Note for anyone editing the Dockerfile: standalone does NOT include
  // .next/static or public/. They are copied separately, and forgetting them
  // serves HTML with no CSS or JS, which reads as a broken build rather than
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

  /**
   * Baseline security headers. There were none.
   *
   * Deliberately NOT a Content-Security-Policy here. A useful CSP for this app
   * has to allow the Windy embed, the backend origin and the WebSocket, and
   * the backend origin is only known at build time from NEXT_PUBLIC_API_URL --
   * so a CSP written blind would either be too loose to mean anything or would
   * break the dashboard in the deployment nobody tests until demo day. It is
   * worth doing properly, separately, with the app running in front of you.
   *
   * These four are unambiguous and cost nothing:
   */
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // The app is never meant to be framed; this is the clickjacking
          // control that does not need a CSP to work.
          { key: "X-Frame-Options", value: "DENY" },
          // Stop the browser second-guessing declared content types.
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Send the origin to other sites, the full path only to ourselves --
          // dashboard URLs can carry district and event context.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // None of these are used, so deny them rather than leaving the
          // decision to a permission prompt.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
