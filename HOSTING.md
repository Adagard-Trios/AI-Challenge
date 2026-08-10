# Hosting from your own machine

Serving the platform from a laptop behind a tunnel, instead of a free-tier
container.

---

## Why this is a reasonable choice

Render's free tier is 512 MB. The API and TensorFlow do not both fit, so three
of the four ML models report `unavailable` there. On a real machine they run
in-process, verified on 14.8 GB / this repo's `requirements.txt`:

```
weather    status=success
currency   status=success
```

So you gain, concretely:

| | Free tier (512 MB) | This machine |
|---|---|---|
| Weather (LSTM), currency (GRU), stock | ⚠️ `unavailable` | ✅ live predictions |
| Anomaly detection | ✅ ONNX MiniLM | ✅ same |
| Playwright browser scrapers | ❌ not installed | ✅ available |
| Cold start | ~50 s after 15 min idle | none |
| Data persistence | wiped on restart | ordinary files |

Three dashboard cards go from "not running on this deployment" to working
inference. That is a real difference to a judge.

## What it costs, stated plainly

The submission requirement is *"a live URL where the application functions as
intended."* A laptop satisfies that **only while it is awake, online, and
running the process.** Judging is often asynchronous, overnight, the next day,
on venue wifi. If the machine sleeps, the link is dead and the requirement is
simply failed, with no partial credit and no way to know it happened.

**So do both.** They do not conflict and neither costs anything:

1. **Keep the Render deployment live** as the always-on URL. It now works
   end-to-end, login, feed, exposure ranking, stories, entities, and real
   anomaly inference. Only the three TensorFlow cards say, accurately, that
   they need a bigger machine.
2. **Use the laptop link as the "full experience"**, mentioned in the README
   and used in the live demo.
3. **Record a video.** The competition guidelines recommend it anyway. A demo
   that depends on a laptop, a tunnel and venue wifi has three things that can
   fail in front of an audience.

Put both URLs in the README, labelled for what they are. That is more
impressive than one URL, not less: it shows you understood the constraint.

---

## 1. Install the full dependency set

`requirements-service.txt` is the slim, deployment set and **deliberately omits
TensorFlow**, installing it is the whole reason to host locally.

```bash
cd backend
pip install -r requirements.txt        # NOT requirements-service.txt
```

## 2. Configure

Create `backend/.env`:

```ini
# Marks this machine as internet-reachable. Escalates the auth checks from
# warnings to refusals, because "acceptable locally" stops being true the
# moment localhost is on the internet.
PUBLIC_HOSTING=1

# Not optional when the URL is public. Without it, anyone with the link can
# write to the API and pair their own connector to your instance.
AUTH_ENFORCED=1
AUTH_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">

# No self-registration exists, so the first account can only come from here.
BOOTSTRAP_ADMIN_EMAIL=you@example.com
BOOTSTRAP_ADMIN_PASSWORD=<a real password>

# Your frontend origin, exactly. Unset means CORS falls back to "*".
CORS_ALLOW_ORIGINS=https://<your-frontend>

GROQ_API_KEY=<key>

# DATABASE_URL is MANDATORY whenever AUTH_ENFORCED=1. This file previously
# said it was optional; that was wrong, and wrong in a way that opens the API.
#
# auth/config.py refuses to fall back to SQLite with enforcement on. It raises
# AuthConfigError -- and main.py catches that with a bare `except Exception`
# and carries on with `require_user()` returning None. The result:
#
#   * /api/auth/login is never mounted, so nobody can log in
#   * every route is public
#   * /ws accepts connections with no ticket
#
# and the public-hosting guard still passes, because it only reads env strings
# and AUTH_ENFORCED really is 1. So the server prints "All checks passed" and
# publishes an unauthenticated API.
#
# Use Postgres (docker compose up -d postgres redis), or start via
# ./start-backend.sh, which refuses to open the tunnel unless the log contains
#     [auth] ready | enforced=True
DATABASE_URL=postgresql+psycopg://roger:roger-local-dev@localhost:5432/roger
```

## 3. Start the backend, the one command

```bash
./start-backend.sh              # data services, backend, tunnel
./start-backend.sh --check      # validate and exit, start nothing
./start-backend.sh --no-tunnel  # services + backend only
```

It fills in any missing public-hosting keys in `.env`, brings up Postgres and
Redis and waits for them to be healthy, starts the backend through
`serve_public.py`, and **refuses to open the tunnel unless the log shows
`[auth] ready | enforced=True`**, see the `DATABASE_URL` note above for why
that guard exists.

It parses `.env` rather than sourcing it, deliberately. `source .env` fails on
this repo twice over: `AUTH_SECRET` contains spaces and is unquoted, so bash
reads it as a command and `start.sh` aborts at that line under `set -e`; and
the file is CRLF, so every sourced value keeps a trailing `\r`, invisible, and
enough to stop `CORS_ALLOW_ORIGINS` matching the frontend origin.

### Publishing at api.nivakaran.dev

A **named** tunnel, not a quick one. `NEXT_PUBLIC_API_URL` is inlined into the
frontend bundle at BUILD time, so a quick tunnel's changing hostname forces a
full Render rebuild on every restart. One-time:

```bash
winget install --id Cloudflare.cloudflared
cloudflared tunnel login
cloudflared tunnel create roger-api
cloudflared tunnel route dns roger-api api.nivakaran.dev
```

`~/.cloudflared/config.yml`:

```yaml
tunnel: roger-api
credentials-file: C:\Users\LENOVO\.cloudflared\<TUNNEL-ID>.json
ingress:
  - hostname: api.nivakaran.dev
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Then on the Render frontend set **both** names and let it redeploy:

```
NEXT_PUBLIC_API_URL  = https://api.nivakaran.dev
NEXT_PUBLIC_API_BASE = https://api.nivakaran.dev
```

Both, because eight components read the first while `AnomalyDetection.tsx` and
`StockPredictions.tsx` read the second, set only one and those two panels call
`localhost:8000` in production. A redeploy is required, not a restart.

WebSockets need nothing extra: `websocketUrl()` derives `wss://` from the same
base with an anchored `replace(/^http/, "ws")`.

## 3b. Or start it by hand

```bash
cd backend
python scripts/serve_public.py
```

It validates first and **refuses to serve** on the dangerous combinations
rather than warning about them, a warning scrolls past, a refusal does not.
`--check` validates and exits.

It binds `127.0.0.1` on purpose. A tunnel connects outward from this machine
and reaches loopback fine; `0.0.0.0` would additionally hand the API to every
device on the local network, which at a venue means everyone at the venue.

## 4. Expose it

**Cloudflare Tunnel** is the right tool here: free, real HTTPS, and, unlike
ngrok's free tier, **no interstitial "you are about to visit" warning page**,
which is not something you want between a judge and your demo.

```bash
# Windows
winget install --id Cloudflare.cloudflared

# quick tunnel: no account, random *.trycloudflare.com URL, prints on start
cloudflared tunnel --url http://127.0.0.1:8000
```

For a URL that survives restarts, a free Cloudflare account plus a domain gives
a *named* tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create roger
cloudflared tunnel route dns roger api.yourdomain.com
cloudflared tunnel run roger
```

A quick tunnel is fine for the deadline; just know the URL changes on every
restart, which means editing the README and rebuilding the frontend each time.

## 5. Point the frontend at it, and rebuild

**This is the step that catches people.** `NEXT_PUBLIC_*` values are inlined
into the client bundle **at build time**, not read at runtime. The browser
calls the backend directly, so changing the URL needs a rebuild, not a restart.

```bash
cd frontend
# .env.local
NEXT_PUBLIC_API_URL=https://<your-tunnel>.trycloudflare.com
NEXT_PUBLIC_API_BASE=https://<your-tunnel>.trycloudflare.com

npm run build && npm run start
```

Set **both**, some components historically read one and some the other, and
the single client in `app/lib/api.ts` honours either so a half-set config
cannot silently send two panels to `localhost:8000`.

The backend must be HTTPS if the frontend is. A browser blocks an HTTPS page
calling `http://localhost`, and it fails as an opaque CORS error rather than
anything that names the real cause. The tunnel gives you HTTPS, so this is
handled, as long as you use the tunnel URL and not the local one.

If you tunnel the frontend too, remember `CORS_ALLOW_ORIGINS` on the backend
must be that exact origin.

---

## Verify, the judge walk

Run this against the **public URL**, from a device that is not this laptop
(phone on mobile data is the honest test, it proves you are not just reaching
your own machine over the LAN).

```bash
curl -s https://<tunnel>/api/status | jq .configuration.healthy   # true
```

1. Dashboard loads.
2. Log in with the bootstrap admin. **Test this specifically**, it is the step
   that fails when `BOOTSTRAP_ADMIN_*` is unset.
3. Set an exposure profile. The feed re-ranks and events show `matched_on`.
4. Stories tab: threaded events with a brief and a derived state.
5. Overview: open a risk index, see the events that moved it.
6. Anomalies: badge reads **ML INFERENCE**, not HEURISTIC.
7. Weather / currency / stock: real predictions, not the "needs a bigger
   machine" card. **This is what local hosting bought you**, if they still say
   unavailable, you installed the slim requirements.
8. Every other card shows a LIVE badge or says plainly why it cannot.

## Before you share the URL

- [ ] `/api/status` reports `"healthy": true`
- [ ] Logging out and back in works
- [ ] `CORS_ALLOW_ORIGINS` is your frontend origin, not `*`
- [ ] The five social accounts whose cookies were previously committed have
      been **rotated**, `backend/src/utils/.sessions/*.json` hold live session
      cookies and this machine is now reachable from the internet
- [ ] Laptop power settings: sleep disabled while presenting
- [ ] Video backup recorded
- [ ] Render deployment still up as the fallback URL

## Sources that cannot be read, and why

These are external constraints, not bugs. Every one of them shows on the card as
`NOT LIVE`, `NO SOURCE` or `FETCH FAILED` rather than as a number.

**waterboard.lk and news.lk sit behind a bot challenge.** Both answer HTTP 307
with no `Location` header and a body of obfuscated JavaScript that computes a
cookie and reloads, served by Sucuri CloudProxy. `requests` cannot follow it,
which is why `_safe_get` records a failure.

No bypass is implemented and none should be. Defeating a WAF is the same line
this project holds on the social scrapers: pacing and hygiene, never evasion.
The legitimate routes are an official NWSDB feed if one is published, an
open-data mirror, or writing to them for access.

**Yahoo Finance carries no Colombo Stock Exchange listing.** `COMB.N0000`,
`COMB.CM`, `JKH.N0000` and `JKH.CM` all return zero rows, which is why the stock
model could never be trained and why the panel once showed US tickers labelled
"CSE" in "LKR". Prices now come from the exchange's own API at
`cse.lk/api/tradeSummary`.

That endpoint is **empty outside market hours** -- it is today's trading, and
outside the session there has been none -- so the tool falls back to
`companyInfoSummery`, which keeps the last close. Quotes carry `as_of` of either
`intraday` or `close` so the card can say which it is showing.

There is still no per-company history endpoint (`chartData` and
`companyPriceHistory` both 400; `dailyMarketSummery` is market-wide aggregates),
so a forecast has to wait for history to accumulate:

```bash
python backend/scripts/snapshot_cse.py            # append today's closes
python backend/scripts/snapshot_cse.py --status   # how much history exists
```

Run it once a day. Until roughly a year of trading days exists the card shows
prices and states that it has no forecast, which is the honest position rather
than a placeholder for one.

**CEYPETCO goes down.** It was unreachable for part of a day and came back. When
it cannot be read, fuel now reports `unavailable` rather than serving the
hardcoded baseline: measured the day the site returned, that baseline said
petrol 92 = 294.00 while CEYPETCO said 414.00, and a figure 120 rupees out under
a small badge is worse than an empty panel.

## Known limitations to state honestly

- The link is up only while the machine is. Say so next to the URL rather than
  letting a judge discover it.
- A quick tunnel's URL changes on restart.
- Collected intelligence lives in `backend/data/`. Back it up; there is no
  second copy.
