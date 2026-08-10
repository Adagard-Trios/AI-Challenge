# Roger — technology choices and operations manual

Supporting document for the Sri Lanka AI Challenge 2026 submission.

`README.md` describes what Roger does. This describes **why it is built the way
it is**, and **how to run it**. Deployment steps live in `DEPLOY.md` (hosted) and
`HOSTING.md` (self-hosted); this does not repeat them.

---

# Part 1 — The stack, and why each piece

| Layer | Choice | Why this one |
|---|---|---|
| Agent orchestration | **LangGraph** | Explicit graph with typed state. The fan-out to five domain agents and the fan-in to one ranked feed is a shape the framework expresses directly, and the state schema makes it a type error rather than a silent empty list when a node forgets to return something. |
| LLM | **Groq** (`openai/gpt-oss-20b` agents, `gpt-oss-120b` chat) | Free tier with 200k tokens/day and very low latency, which matters because classification sits on the path between collection and the feed. Model IDs resolve through `src/llms/models.py` rather than being pinned at call sites, after a deprecated ID returned 404 on every chatbot message for days. |
| API | **FastAPI** | Async, and its dependency system is what makes `require_user` a single declaration per route instead of a check that can be forgotten. |
| Relational store | **PostgreSQL** | Users, sessions, ingested posts, stories, the blackboard ledger. Chosen over SQLite because the deployment is multi-process: the agent loop, the API and the collector all write. |
| Cache / coordination | **Redis** | Scrape pacing, cross-replica dedup, shared dashboard state, single-use WebSocket tickets. Pacing in particular *must* be shared — three replicas with per-process counters each spend a full allowance against one social account. |
| Vector store | **ChromaDB** | Embedding search for the RAG assistant and for near-duplicate detection. |
| Embeddings | **ONNX all-MiniLM-L6-v2**, 384-dim | Replaced 768-dim distilBERT, which the deployed image could not produce — and whose vectorizer returned `np.zeros(768)` on failure, so every event scored identically while the endpoint reported `ml_active`. |
| Forecasting | **Keras** LSTM (weather), GRU (currency) | Sequence models over daily series. They run in-process on the host, which is the reason the API is hosted there rather than on a 512 MB instance. |
| Anomaly detection | **scikit-learn** isolation forest | Cheap, no GPU, and interpretable enough to explain a score. |
| Scraping | **Playwright** + **BeautifulSoup** | Playwright only where a real browser is genuinely needed — a human completing a social login, including 2FA. Everything else is plain HTTP. |
| Frontend | **Next.js**, React, Tailwind | Static export served by Render. `NEXT_PUBLIC_*` is inlined at build time, so the API URL is a rebuild, not a restart. |
| Public access | **Cloudflare Tunnel** | Connects **outward** from the host, so no router port is opened and the home IP is never published. Works behind CGNAT. Unlike ngrok's free tier there is no interstitial page between a judge and the demo. |

## The decisions that are not obvious

**Fan-out, not a hierarchy.** Five domain agents run in parallel and their
outputs are merged by one aggregator. A supervisor deciding which agent to call
would add a round of LLM latency per cycle to choose between agents that should
all run anyway.

**The blackboard runs in shadow.** `src/blackboard/` computes what an
opportunistic scheduler *would* run each cycle and records that decision, while
the existing fan-out keeps collecting. This is deliberate. Opportunistic control
produces *less* data, not obviously smarter data, and "the feed looks dead" is a
failure this project has hit more than once. The ledger exists to prove the
triggers are right before anything is handed over. Set `BLACKBOARD_CONTROL=active`
only once the ledger shows sensible decisions.

**Credentials are per user and never leave the machine.** Each user's social
passwords and browser sessions live under `users/<sha256(user_id)>/` with their
own encryption key derived from that directory, sealed with AES-256-GCM and the
OS keyring. Two accounts cannot reach each other's connections. The user id is
hashed because it reaches a filesystem path.

**Collection is paced, never evasive.** Every scrape passes a shared pacing gate
and a daily budget. Automated collection breaches these platforms' terms; the
budget bars exist so an operator can ease off before a restriction lands, not
because one cannot happen. Where a source sits behind a bot challenge —
`waterboard.lk` and `news.lk` both serve a Sucuri JavaScript challenge — **no
bypass is implemented**, and the card reports the failure honestly.

**No facial recognition**, anywhere, by design. Sri Lanka's Personal Data
Protection Act No. 9 of 2022 governs biometric processing, and image handling is
limited to OCR of text in posts.

**Refusal over fabrication.** Where a model cannot produce an answer, the API
returns `unavailable` and the card says so. This is enforced by tests, because
it was violated twice: the stock panel served simulated prices as
`{"status": "success"}` with an 80% confidence badge, and the currency card
returned a fallback anchored to a hardcoded 298.0 while the real rate was 335.

---

# Part 2 — Operations manual

## Starting and stopping

```bash
./start-backend.sh                 # data services, backend, tunnel
./start-backend.sh --check         # validate configuration and exit
./start-backend.sh --no-tunnel     # services + backend only
```

**Use this rather than starting the backend by hand.** It refuses to open the
tunnel unless the log shows `[auth] ready | enforced=True`. Starting
`serve_public.py` directly skips that gate — which is how, once, a restart with a
briefly-unavailable database published an API where every route was readable and
writable by anyone with the URL, while `/healthz` returned 200 throughout.

Stopping is whatever kills the process; state is in Postgres, Redis and the
filesystem, so nothing is lost.

## Daily and periodic tasks

```bash
# Append today's CSE closes. Run daily; a stock model needs ~1 year of these.
python backend/scripts/snapshot_cse.py
python backend/scripts/snapshot_cse.py --status

# Collect from connected social accounts on this machine.
python backend/scripts/collector.py --once
python backend/scripts/collector.py            # loop, every 15 minutes

# Remove feed rows whose summary was cut mid-sentence by an older limit.
python backend/scripts/drop_truncated_feeds.py --apply
```

## Retraining

```bash
cd models/weather-prediction              && python main.py --mode full
cd models/currency-volatility-prediction  && python main.py --mode train --period 5y --epochs 80
```

Anomaly detection retrains automatically at backend startup when no artifact is
found. After retraining currency, delete any cached prediction under
`output/predictions/` or the endpoint will keep serving the old one.

**Check the numbers before trusting them.** The currency model reports direction
accuracy and mean error in the training log; a next-day USD/LKR forecast moving
more than a fraction of a percent is a sign something is wrong, not a signal.

## Environment variables that matter

| Variable | Effect |
|---|---|
| `AUTH_ENFORCED` | `1` requires a token on every route. The backend now **refuses to start** if this is on and auth fails, rather than serving unauthenticated. |
| `DATABASE_URL` | Mandatory whenever auth is enforced. Without it the auth layer cannot initialise. |
| `GROQ_API_KEY` | Required. Quotas are **per model per day**; switching `GROQ_MODEL` changes which budget you spend. |
| `DEMO_PREDICTIONS` | `1` fills the currency and CSE cards with illustrative values for a recorded walkthrough. Off by default. Read per request, so no restart. |
| `BLACKBOARD_CONTROL` | `shadow` (default) plans and records. `active` hands collection to the controller. |
| `ALLOW_SELF_REGISTRATION` | `1` lets anyone with the URL create an account. Safe because accounts are isolated, but it is a decision. |
| `CORS_ALLOW_ORIGINS` | Exact frontend origin. Unset falls back to `*`. |

## Health checks

```bash
curl -s https://api.nivakaran.dev/healthz     # {"ok": true}
curl -s https://api.nivakaran.dev/readyz      # database reachable
curl -s https://api.nivakaran.dev/api/status  # per-feature configuration report
```

`/api/status` is the one to read: it names which capabilities are live and which
are not, rather than answering a single boolean.

---

# Part 3 — Failure modes, and what each looks like

Every entry here has actually happened. The signature matters more than the fix,
because each one presented as something other than what it was.

| Symptom | Actual cause |
|---|---|
| Dashboard visible without signing in | `/api/me` answers 401 when signed out, the client's `enforced` flag defaulted to `false`, so the gate opened. Now defaults closed. |
| `/api/auth/login` returns 404 and every route is public | The auth layer failed to initialise and was swallowed. `/healthz` still returns 200. The backend now refuses to start. |
| Six situational cards read `NO SOURCE` | The fetch ran before sign-in, 401'd, and nothing retried for five minutes. Now marks the failure and retries at 15/30/60s. |
| Feed stops updating, dashboard shows "Cycle 0" | The cycle counter was never published to shared state. Check the log for `Cycle #N completed` — if that line advances, the pipeline is fine. |
| Every event marked `llm_filtered: false` | Groq daily token cap. Quotas are per model; check the 429 body, which names the limit and the model. |
| Fuel prices look wrong | CEYPETCO goes down intermittently. Past 60 days the baseline is now refused rather than served. Compare against `ceypetco.gov.lk` directly. |
| Water or news cards say `FETCH FAILED` | Sucuri bot challenge, HTTP 307 with no `Location`. Not fixable without evading it, which this project does not do. |
| `api.nivakaran.dev` returns 530 | The tunnel process died. The backend can be perfectly healthy on `127.0.0.1:8000`. Restart `cloudflared tunnel run roger-api`. |
| Social panel shows no accounts | Either a failed request (now says so) or a vault that cannot be decrypted (now logged). Check the backend log for `[vault]`. |
| Non-browser clients get HTTP 403 | Cloudflare's browser-integrity check, error code 1010. Browsers are unaffected; `curl` needs a normal user agent. |

## The pattern behind most of these

Nearly every entry above is one shape: **a failure that reported success.** A
default that means "fine", an `except` that returns an empty list, an `if ok:`
with no `else`. Individually each is defensible; together they made the system
unable to say when it was broken.

That class is now enforced rather than remembered.
`backend/tests/unit/test_failures_are_visible.py` walks the codebase and fails
the build on a handler that returns an empty result without logging, or that
claims a success status from inside an exception. If you add code here, that
test is the one to read first.

---

# Testing

```bash
cd backend && pytest tests/unit -q      # 851 tests
cd frontend && npm run build            # type-checks and builds
```

The suite is unusual in one respect worth mentioning: a large share of it pins
*honesty* properties rather than behaviour — that no route serves the shared
vault, that two user ids never resolve to one directory, that the stock endpoint
never emits a predicted price while no model exists, that the README does not
advertise a forecast that cannot be produced. Those are the invariants that
regressed most often, so they are the ones written down.
