# Roger — frontend

The dashboard for the Roger Intelligence Platform: district-level flood, power,
water, health and economic alerts for Sri Lanka. Next.js 16, React 19,
Tailwind 3, TypeScript.

This file used to be the unmodified `create-next-app` boilerplate.

## Running it

```bash
npm ci
npm run dev          # http://localhost:3000
```

The dashboard expects the backend on `http://localhost:8000`. Without it the
app still runs — every panel has an explicit "no data" state, and the WebSocket
retries with backoff — so the UI is workable on its own.

```bash
npm run build && npm start   # production build, port 3000
npm run lint
npx tsc --noEmit
```

**Test the production build, not just `next dev`.** A crash that blanked the
whole dashboard on an unexpected-but-valid API response only reproduced in a
production build; `next dev`'s error overlay hid it. `.claude/launch.json` has a
`frontend-prod` entry for this.

## Configuration

Both variables must be set, to the same value:

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend base URL |
| `NEXT_PUBLIC_API_BASE` | Same value — some modules read this name |

`NEXT_PUBLIC_*` is inlined at **build** time, not read at runtime. Changing
either needs a rebuild, not a restart — setting them in `docker run` does
nothing. See `frontend/Dockerfile` and `frontend/render.yaml`.

## How it is put together

| Path | What lives there |
|---|---|
| `app/lib/api.ts` | The only HTTP client. Access token in memory, rotating refresh token, one shared in-flight refresh |
| `app/lib/severity.ts` | The single severity scale (DMC / WMO / CAP warning ladder) |
| `app/lib/format.ts` | Display formatting. Returns `—` rather than `Invalid Date` or `NaN%` |
| `app/hooks/use-roger-data.tsx` | One WebSocket and one poll loop for the whole app, via `RogerDataProvider` |
| `app/components/PanelBoundary.tsx` | Per-panel error boundary so one bad response cannot blank the page |
| `app/globals.css` | Design tokens. `:root` is light, `.dark` is dark |

### Two rules worth knowing before you edit

**Absence is not zero.** A missing value renders as `—` in muted grey, never as
`0%` in green. `RiskDashboard`'s index fields are `number | null` for this
reason, and the power/water/health cards branch three ways — active, normal,
*no reading* — rather than two. On a warning system, silence must never render
as an all-clear.

**Severity comes from `lib/severity.ts`.** Do not write a local colour map; six
of them had drifted apart, and one sent `medium` to green, which on the warning
ladder means *no warning in force*.

## Known gaps

- The app is a react-router SPA mounted at `/`, inside the App Router. There is
  one route, so there is no code splitting and every client route needs a
  rewrite in `next.config.ts` (see `/login`).
- No unit tests. `tests/e2e/qa.mjs` needs an external browser harness and a live
  backend, so it does not run in CI.
- `npm run lint` reports 5 `react-hooks/set-state-in-effect` errors, from async
  fetches in effects. Clearing them means moving data fetching to react-query.
- No Content-Security-Policy — it needs the backend origin, which is only known
  at build time. Other baseline headers are set in `next.config.ts`.
