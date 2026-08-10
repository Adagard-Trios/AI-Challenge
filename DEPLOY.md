# Deploying, Render (+ Vercel option for the frontend)

Six deployables, each with its own blueprint:

| # | Service | Source | Blueprint | Platform |
|---|---|---|---|---|
| 1 | Backend API | `backend/` | `render.yaml` | Render (Docker) |
| 2 | Weather model | `models/weather-prediction/` | `models/weather-prediction/render.yaml` | Render (Docker) |
| 3 | Currency model | `models/currency-volatility-prediction/` | same folder | Render (Docker) |
| 4 | Stock model | `models/stock-price-prediction/` | same folder | Render (Docker) |
| 5 | Anomaly model | `models/anomaly-detection/` | same folder | Render (Docker) |
| 6 | Frontend | `frontend/` | `frontend/render.yaml` | Render web service (or Vercel) |

**The model services are required in deployment, optional locally.**

- *Locally* (full `requirements.txt`) the backend runs all four models in-process, exactly as
  before, and only calls a model over HTTP when its `*_SERVICE_URL` is set.
- *Deployed* the image installs the slim `requirements-service.txt`, which has no ML framework,
  so each model must have its `*_SERVICE_URL` pointing at its own service. Without one, that
  model's endpoints return the gateway's "unavailable" response. See §1.2.

Deploy order: **model services → backend → frontend.** Each step needs the previous URL.

> Splitting the models out also removes the reason for `main.py`'s `sys.path`/`sys.modules` surgery:
> all four projects define a top-level package named `src`, which cannot coexist in one interpreter
> but is a non-issue once each runs in its own container.

---

## 0. Model services (optional, deploy first)

Each model folder is self-contained: `service.py` (FastAPI), `Dockerfile`, `requirements-service.txt`
(serving deps only, no mlflow/optuna/dagshub), and `render.yaml`.

Apply each blueprint separately: **New → Blueprint →** this repo → point at that model's
`render.yaml`. `rootDir` scopes the build context to the model folder.

| Service | Endpoints | Plan | Notes |
|---|---|---|---|
| `slac2026-weather` | `/health` `/model/status` `/predict` `/predict/{district}` | free | TensorFlow, **tight on 512 MB** |
| `slac2026-currency` | `/health` `/model/status` `/predict` | free | TensorFlow, **tight on 512 MB** |
| `slac2026-stock` | `/health` `/model/status` `/predict` `/predict/{symbol}` | free | no TensorFlow, the one that fits comfortably |
| `slac2026-anomaly` | `/health` `/model/status` `POST /detect` | free | fine on the default heuristic tier; ML tier will OOM |

`/health` never touches TensorFlow or Torch, so it answers instantly and Render's health check
passes long before the first (lazy) model load.

### Known gaps these services report honestly

- **Currency**: live inference needs `artifacts/models/training_config.json`, which is **not
  committed**. Until it exists the service answers on its fallback tier and `/model/status` returns
  `"live_inference_available": false`.
- **Stock**: the predictor looks for `Artifacts/<timestamp>/model_trainer/trained_model/model.pkl`
  while the committed artifact is `artifacts/models/stock_model.pkl`. Predictions come from its
  simulated fallback; `/model/status` exposes `predictor_artifacts_found`. Note this resolves
  differently on Linux than on Windows, where `Artifacts` matches `artifacts` case-insensitively.
- **Anomaly**: this model no longer needs a separate service. It runs **in the backend
  container** on 384-dim ONNX MiniLM embeddings, which chromadb already ships and the slim
  image already carries. Leave `ANOMALY_SERVICE_URL` unset. See below for why.

### Anomaly detection: why it moved in-process

The committed `isolation_forest_{english,tamil}.joblib` models take 768-dim distilBERT
vectors from `models/anomaly-detection/src/utils/vectorizer.py`, which needs
`transformers` + `torch`, the ~3 GB stack `requirements-service.txt` deliberately omits.

**That vectorizer does not fail when they are missing. It returns `np.zeros(768)`.**
Measured with both blocked exactly as the deployed image has them:

```
nonzero_dims=0  pred=-1  score=+0.012138   Heavy flooding in Ratnapura...
nonzero_dims=0  pred=-1  score=+0.012138   Colombo Port operating normally...
nonzero_dims=0  pred=-1  score=+0.012138   Central Bank holds rate steady...
```

Every event identical, every event flagged anomalous, `/api/anomalies` reporting
`model_status: "ml_active"` throughout. Fabricated output presented as inference.

So the shipped model is re-fitted on embeddings the container can actually compute:

```bash
cd backend && python scripts/train_anomaly_minilm.py
```

It writes `isolation_forest_minilm.joblib` plus a sidecar `.json` recording the corpus
size and contamination, and **refuses to write anything** if the model flags more than
3× its configured rate on held-out data. `/api/model/status` returns that card, and
`/api/anomalies` returns `is_ml` so the dashboard can never present the heuristic
fallback as machine learning.

---

## 0.5 Social accounts: the connector

Social collection does **not** run on this server. It runs in `connector/`, on the
user's own machine.

```
USER'S MACHINE                        RENDER
┌────────────────────────────┐       ┌──────────────┐
│ python -m connector run     │       │ backend      │
│  · sessions encrypted here  │──────▶│  /api/ingest │
│  · Playwright here          │ posts │  no browser  │
│  · user's own IP            │       │  no cookies  │
└────────────────────────────┘       └──────────────┘
```

Two reasons, and they reinforce each other:

- **Credentials never transit.** The server has nowhere to put a cookie, see
  `backend/auth/models.py`, and the test that fails if a cookie-shaped column ever
  appears. A database compromise yields no account access.
- **Requests come from the user's own IP**, carrying a session created on that
  same IP. Presenting a residential session from a datacenter is one of the
  strongest bot signals there is, and no browser-flag tuning addresses it.

Setup:

```bash
# in the dashboard: Settings → Accounts → Get pairing code
python -m connector pair 123-456-789 --server https://roger-backend.onrender.com
python -m connector connect linkedin      # opens a real browser; you log in
python -m connector run "Sri Lanka economy"
```

**Connecting requires a desktop, once per platform.** Every platform stores its
login in an httpOnly cookie (`auth_token`, `xs`, `sessionid`, `li_at`, verified
against real captures), which no web page can read. There is no bookmarklet or
mobile path that can capture a session. Everything else works on a phone.

`connector connect --paste <file>` accepts a DevTools export, so the pipeline is
testable before signed installers exist.

**Terms of service.** Automated collection violates the terms of X, LinkedIn,
Facebook and Instagram regardless of how the session was obtained or where it
runs. Accounts can be restricted. Local collection lowers the risk; it does not
remove it. The UI states this before anyone connects.

---

## 0.6 Auth

`AUTH_ENFORCED=0` by default: routes resolve a user when a token is present and
work anonymously otherwise, so the frontend can migrate before cutover.

| Variable | Required when enforced | Notes |
|---|---|---|
| `DATABASE_URL` | **yes** | Postgres, **Supabase**. See below. Refuses to start without it, rather than falling back to a SQLite file that Render wipes on every restart. |
| `AUTH_SECRET` | **yes** | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `AUTH_ENFORCED` |, | `1` to require auth |
| `BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` |, | Seeds the first admin, once, only when no users exist |

**Use the Supabase connection pooler, not the direct connection.** Two reasons:

- Supabase's *direct* connection (`db.<ref>.supabase.co:5432`) is **IPv6-only** on new
  projects unless you buy the IPv4 add-on. Outbound IPv6 is not something to assume on a
  host you do not control. The pooler answers on IPv4.
- Render free spins down and Supabase free pauses after ~7 days idle, so connections are
  torn down constantly. A pooler absorbs that.

Copy the **Transaction pooler** string from Supabase → Project Settings → Database:

```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
```

`auth/db.py` detects port 6543 and adapts: `NullPool` (pooling on top of PgBouncer is worse
than not pooling) and `prepare_threshold=None`. That second one matters, psycopg3 prepares
statements automatically after a few executions, and a prepared statement does not survive
PgBouncer's transaction multiplexing. It surfaces as `prepared statement "_pg3_0" already
exists` *once traffic warms up*, not at startup, which makes it look random.

Session-mode (port 5432 on the pooler host) also works and keeps prepared statements; it
uses more connections. Either is fine, the code handles both.

⚠️ **Supabase free pauses a project after ~7 days of inactivity** and needs a manual restore
from the dashboard. For a dashboard nobody opens over a holiday, that is a real failure mode.

Cutover: deploy → create the admin → log in → confirm → set `AUTH_ENFORCED=1`.
One env var, instantly revertible. `/api/status` stays public (`render.yaml` uses
it as the health check).

### 0.7 Verify the deployment without shell access

`/api/status` carries a `configuration` block naming every unset variable **and what it
broke**. It reports whether a value exists, never the value.

```bash
curl -s https://<backend>/api/status | jq .configuration
```

```json
{
  "healthy": false,
  "failures": [
    { "key": "DATABASE_URL",
      "consequence": "Falling back to SQLite on the container's ephemeral disk. Every account, exposure profile, story and paired device is destroyed on the next deploy, restart or spin-down.",
      "detail": "Set the Supabase transaction-pooler URL (port 6543)." }
  ],
  "warnings": [ ... ],
  "configured": ["AUTH_SECRET", "GROQ_API_KEY", "anomaly_model"]
}
```

This exists because the failure mode here is always the same shape: missing configuration
degrades into something that *looks* like it works. A missing `DATABASE_URL` silently
becomes ephemeral SQLite. A missing `BOOTSTRAP_ADMIN_EMAIL` makes the seeder return early
with no log line, so **nobody can ever log in** and nothing anywhere says why. Both are
reasonable local defaults and production outages.

The same problems are logged at ERROR on startup. `"healthy": true` with an empty
`failures` array is the green light.

---

## 1. Backend → Render

Backend = FastAPI + LangGraph (`backend/`), deployed as a **Docker** service on Render.

To use the model services, set these on the backend (omit any to keep that model in-process):

```
WEATHER_SERVICE_URL  = https://slac2026-weather.onrender.com
CURRENCY_SERVICE_URL = https://slac2026-currency.onrender.com
STOCK_SERVICE_URL    = https://slac2026-stock.onrender.com
ANOMALY_SERVICE_URL  = https://slac2026-anomaly.onrender.com
MODEL_SERVICE_TIMEOUT = 60      # optional, seconds
```

Verify the wiring with **`GET /api/status`** and **`GET /api/models/health`**, the latter reports
`mode: in-process | remote` and reachability per model.

### 1.1 Why Docker and not a Python service

Reproducible builds and full control of the base image. Note the original reason,
Playwright + Chromium, no longer applies: the browser was removed once collection
moved to the connector, taking ~400 MB out of the image and Chromium's
100-300 MB resident footprint off a 512 MB instance.

**Known cost of that removal:** two session-*free* scrapers, `rivernet`
(`utils.py:513`) and the weather nowcast (`utils.py:2093`), are browser-driven and
so no longer work server-side. They need no user account, so they belong in a small
browser-capable service or an HTTP rewrite, not back in this image.

### 1.2 Two requirement sets, this is what fixes the OOM

| File | Used by | Contents |
|---|---|---|
| `requirements.txt` | local dev | Full set, **3.12 GB installed**, includes TensorFlow, PyTorch and the training stack so models can run **in-process** |
| `requirements-service.txt` | `backend/Dockerfile` | Slim runtime set, no TensorFlow, PyTorch, sklearn, mlflow or training deps |

The deployed backend does not need any ML framework: the four models run as their own services and
the backend calls them over HTTP via `src/model_gateway.py`.

**The subtle part.** The backend has *no module-level import* of torch or tensorflow anywhere.
But `langchain_groq.chat_models` imports `transformers` **if it happens to be installed**, and
`transformers` then imports `torch`, roughly 3 GB of resident stack pulled in by accident, purely
because the packages were present. Verified by blocking both modules: `from langchain_groq import
ChatGroq` and `ChatGroq(...)` still work. Not installing them removes the import entirely.

ChromaDB is unaffected, `chromadb_store.py` passes `CHROMADB_EMBEDDING_MODEL` as collection
*metadata* only, so Chroma uses its bundled ONNX embedder, not sentence-transformers.

**Consequence:** with the slim set, the in-process fallback cannot work. Every model endpoint needs
its `<MODEL>_SERVICE_URL` set, or the gateway returns its unavailable response. That is the intended
deployed topology, deploy the four model blueprints first.

### 1.3 Deploy

**Blueprint (recommended)**, Dashboard → **New** → **Blueprint** → select this repo. It reads
`render.yaml` and provisions the service and env-var slots.

**Manual**, New → Web Service → Docker, then set:

| Setting | Value |
|---|---|
| Dockerfile Path | `./backend/Dockerfile` |
| Docker Build Context | `.` (**repo root, not `backend/`**) |
| Health Check Path | `/api/status` |
| Disk | none, free tier does not support persistent disks |

The build context **must** be the repo root: the image needs `models/`, which is a sibling of
`backend/`, because `main.py` resolves it as `Path(__file__).parent.parent / "models"`.

### 1.4 Environment variables

Set in the Render dashboard (the `sync: false` entries in `render.yaml` are deliberately blank):

| Variable | Value | Required |
|---|---|---|
| `GROQ_API_KEY` | your Groq key | **Yes**, the app raises at import without it |
| `DISABLE_AUTO_TRAIN` | `1` | **Yes**, see §1.5 |
| `AGENT_LOOP_START_DELAY` | `45` | **Yes on free**, see §1.7 |
| `DISABLE_AGENT_LOOP` | `0` (or `1` to disable scraping) | No |
| `CORS_ALLOW_ORIGINS` | frontend origin, e.g. `https://slac2026-frontend.onrender.com` | Strongly recommended |
| `SQLITE_DB_PATH` | `/app/backend/data/cache/feeds.db` | Pre-set in `render.yaml` |
| `CHROMADB_PATH` | `/app/backend/data/chromadb` | Pre-set |
| `CSV_EXPORT_DIR` | `/app/backend/data/feeds` | Pre-set |
| `NEO4J_ENABLED` | `false` | Pre-set |
| `LANGSMITH_API_KEY` | optional tracing | No |

Do **not** set `PORT`, Render injects it, and `start_backend.sh` already binds `0.0.0.0:$PORT`.

### 1.5 Why `DISABLE_AUTO_TRAIN=1` is mandatory

`main.py` calls `check_and_train_models()` at *import*, which forks ML training subprocesses with a
30-minute timeout. On Render that runs on every cold start and will OOM the instance before it can
bind `$PORT`. The gate makes it a no-op. Trained artifacts are already committed under
`models/*/artifacts/`, so nothing is lost.

Retrain locally or via the Airflow DAGs in `airflow/`, then commit the updated artifacts.

### 1.6 Storage is ephemeral on the free plan

`backend/data/` holds the SQLite dedup cache and the ChromaDB vector store. **Render's filesystem is
ephemeral, and the free plan cannot mount a persistent disk**, so every deploy, restart and
spin-down wipes all collected intelligence and the dedup layer restarts from zero. The agent loop
re-collects, but nothing accumulates across restarts.

To persist it, move to a paid plan and add a disk back to `render.yaml`:

```yaml
    disk:
      name: roger-data
      mountPath: /app/backend/data
      sizeGB: 10
```

Trade-off once you do: a disk pins the service to **one instance** and **disables zero-downtime
deploys**. Acceptable here, the app runs a singleton 60s agent loop and isn't horizontally
scalable anyway.

### 1.7 First boot, and why the agent loop is delayed

Cold start is slow: `import main` compiles six LangGraph graphs and opens ChromaDB. **Measured at
~28 s on a fast local machine**, so expect appreciably longer on a shared-CPU free instance. Uvicorn
imports the app *before* binding `$PORT`, so nothing answers until that finishes.

Then the real hazard. Historically the graph thread began a full agent cycle the instant the port
bound, fanning out to five scraping agents and launching Playwright Chromium. On a small instance
that starves `/api/status` past Render's **5 second** health-check timeout. Render kills the
instance, the restart begins another cycle, and it never converges:

```
HTTP health check failed (timed out after 5 seconds) while running your code.
Instance failed
```

`AGENT_LOOP_START_DELAY` (default **45** s) holds the first cycle back so health checks pass first.
Set `0` for the old behaviour. If it still flaps, `DISABLE_AGENT_LOOP=1` serves the API with no live
collection at all, useful to confirm the rest of the service is healthy.

The 2 s database poll also runs its SQLite read in a thread executor rather than inline, so it
cannot stall the event loop between cycles.

Startup log should show:

```
[STARTUP] Auto-training disabled (DISABLE_AUTO_TRAIN set)
[SQLiteCache] Initialized at /app/backend/data/cache/feeds.db
[ChromaDB] Initialized collection: Roger_feeds
[API] Graph thread started
[GRAPH THREAD] Waiting 45s before first cycle (AGENT_LOOP_START_DELAY) so health checks can pass
```

Smoke test:

```bash
curl https://<service>.onrender.com/api/status
curl https://<service>.onrender.com/api/weather/model/status   # {"models_trained": 5}
curl https://<service>.onrender.com/api/currency/model/status  # {"model_exists": true}
```

---

## 2. Frontend → Render (web service) or Vercel

The frontend is a **dynamic app**: it polls the backend's REST endpoints, holds an open WebSocket for
live feed updates, and re-renders continuously. It runs as a real Next server (`next start`), so
server-side features stay available, API routes, server actions, SSR, middleware, even though the
current dashboard renders client-side.

Pick **one** host.

### 2A. Render, Node web service

Apply `frontend/render.yaml`: **New → Blueprint →** this repo → point at that file.

| Setting | Value |
|---|---|
| Runtime | `node` |
| Root Directory | `frontend` |
| Build | `npm ci --include=dev && npm run build` |
| Start | `npm start -- -p $PORT` |
| Plan | `free` |

Two free-plan caveats:

- **512 MB RAM.** The running Next server fits comfortably; `next build` is the tighter step. If the
  build gets OOM-killed, raise `plan:` or set `NODE_OPTIONS=--max-old-space-size=460` so V8 collects
  harder instead of letting the container OOM.
- **Spin-down after ~15 min idle.** The next visitor pays a cold start while Node boots.

`--include=dev` is required: `typescript`, `tailwindcss` and `babel-plugin-react-compiler` are
devDependencies needed at build time, and a bare `npm ci` skips them if `NODE_ENV=production` is set.

### 2B. Vercel

Connect Vercel directly to this repo, it builds `frontend/` in place, and its Git integration
handles push-to-deploy (there is no CI step for the frontend, and none is needed).

| Setting | Value |
|---|---|
| **Root Directory** | `frontend` ← **required**, this is a monorepo |
| Framework Preset | Next.js (auto-detected) |
| Install Command | `npm ci` (already in `frontend/vercel.json`) |

**Do not change the install command back to `npm install`.** Four packages, `clsx`,
`@radix-ui/react-slot`, `@radix-ui/react-dialog`, `@radix-ui/react-collapsible`, are imported by the
UI but *not declared* in `package.json`. They resolve only as hoisted transitives from the committed
lockfile. `npm install` may re-resolve and fail the build.

### 2C. Environment variables, set **both** (either host)

The codebase reads two different names: 8 files use `NEXT_PUBLIC_API_URL`, but
`app/components/dashboard/AnomalyDetection.tsx` and `app/components/dashboard/StockPredictions.tsx`
use `NEXT_PUBLIC_API_BASE`. Set **both to the same value** or those two panels will silently fall
back to `http://localhost:8000` in production:

```
NEXT_PUBLIC_API_URL  = https://<service>.onrender.com
NEXT_PUBLIC_API_BASE = https://<service>.onrender.com
```

No trailing slash. These are inlined at build time, **changing them requires a redeploy**, not just
a restart.

### 2D. WebSocket

`use-roger-data.ts` derives the socket URL as `API_BASE.replace('http','ws') + '/ws'`, so an
`https://` backend correctly becomes `wss://…/ws`. The socket is opened by the browser straight to
the backend, so it never traverses the frontend server, the choice of host is irrelevant to it.

Note the backend must be awake for the socket to connect. On free tier it spins down after ~15 min
idle, so the first dashboard load after a quiet period sits on the loading screen until the backend
cold-starts (`use-roger-data.ts` retries every 1 s and falls back to REST polling meanwhile).

---

## 3. Order of operations

1. *(Optional)* Apply the four model blueprints; wait for each `/health` to return 200.
2. Deploy backend to Render, setting any `*_SERVICE_URL` you want routed remotely.
3. Confirm `GET /api/models/health` shows the modes you expect.
4. Copy the backend URL.
5. Deploy frontend to Vercel with Root Directory `frontend` and **both** env vars set.
6. Copy the Vercel URL into the backend's `CORS_ALLOW_ORIGINS` (and each model service's, if you
   call them directly from the browser); let them redeploy.
7. Open the Vercel URL, the dashboard should populate within ~2 minutes of the backend's agent loop.

### Plan note

**All five blueprints ship with `plan: free`.** That costs nothing, and it comes with three
constraints worth knowing before you debug a "broken" deploy:

| Constraint | Effect |
|---|---|
| 512 MB RAM | The backend (3.12 GB of deps) is expected to OOM during import. Weather and currency are borderline once TensorFlow loads. Stock and anomaly (heuristic tier) are fine. |
| No persistent disks | Free plans cannot mount one. SQLite/ChromaDB state and generated predictions are wiped on every restart. |
| Spin-down after ~15 min idle | The next request pays a full cold start, minutes for the TensorFlow/PyTorch services. |

Realistically: **stock and anomaly run well on free**; weather and currency will be flaky; the
backend needs `standard` (2 GB) to stay up. Raise `plan:` per service as needed, they are
independent, so you can pay for only the backend and leave the four model services free.

Remember the model services are opt-in: leaving all four `*_SERVICE_URL` vars unset runs every
model in-process and costs exactly one service.

---

## 4. Security

- **`backend/src/utils/.sessions/*.json` contains live session cookies** for real Facebook,
  Instagram, LinkedIn, Reddit and X accounts, and is a **local-only artifact**.
  - *Not* in git, `.gitignore:27` is `**/.sessions/`; verified 0 files tracked and 0 in history.
  - *Not* in a Render image, Render builds from the git clone, so the directory is simply absent.
    This is also why every session-dependent scraper currently returns
    `{"error": "No <Platform> session found"}` in production.
  - **Was** copied into any image built locally, because the build context is the working tree and
    `.dockerignore` did not exclude it. Fixed, `.dockerignore` now excludes `**/.sessions` and
    `**/*storage_state.json`. **Rotate those five accounts**: an image layer keeps the file even
    after a later `RUN rm`.

  Sessions are moving to the user's own machine (see the connector). The server will not store
  social credentials at all.
- `CORS_ALLOW_ORIGINS` defaults to `*`. When it is `*`, credentials are automatically disabled
  (the CORS spec forbids that combination and browsers reject it). Set a real origin in production.
- `GROQ_API_KEY` must only ever come from the Render dashboard, never commit it. `.env` is
  gitignored and `.dockerignore`d.

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Build pulls `nvidia-cuda-*` wheels, image ~6 GB | CPU pin missing | `backend/requirements.txt` must keep `--extra-index-url https://download.pytorch.org/whl/cpu` and `torch==2.9.1+cpu` |
| Build runs out of disk / times out | Build context too large | Ensure `.dockerignore` exists at the **repo root** (excludes `node_modules`, `.venv`, `.next`) |
| Service unreachable after a quiet period | Free tier spins down after ~15 min idle | Expected; first request pays a cold start. Paid plans stay warm |
| Service restarts in a loop, "Out of memory" | Image built from `requirements.txt` (3.12 GB) instead of `requirements-service.txt`, or auto-train ran | Confirm `backend/Dockerfile` installs `requirements-service.txt`; set `DISABLE_AUTO_TRAIN=1` |
| Health check never passes | Cold start slower than the window | Raise the grace period; confirm `$PORT` is not overridden |
| All feeds vanish after a deploy | Free tier has no persistent disk, expected | Move to a paid plan and attach a disk at `/app/backend/data` |
| Anomaly + Stock panels empty, rest fine | Only one env-var name set | Set `NEXT_PUBLIC_API_BASE` too (§2.2) |
| Browser console: CORS error | Origin not allowlisted | Set `CORS_ALLOW_ORIGINS` to the exact Vercel origin, no trailing slash |
| Vercel build: "Module not found: clsx" | `npm install` re-resolved deps | Restore `npm ci` |
| `[MODEL CHECK] ⚠ Anomaly Detection - No model found` | Pre-existing upstream quirk, `main.py` checks `artifacts/models`, files are in `artifacts/model_trainer/` | Harmless with `DISABLE_AUTO_TRAIN=1`; anomaly endpoints degrade gracefully |
| `/api/models/health` shows `in-process` when you expected `remote` | `*_SERVICE_URL` unset or empty on the backend | Set it, then redeploy the backend |
| Model endpoints answer but ignore the model service | Service unreachable, gateway fell back silently | Check backend logs for `[gateway] … call failed`; hit the service's `/health` directly |
| Model endpoints return "unavailable" | `<MODEL>_SERVICE_URL` unset, and the slim image has no ML framework for the in-process path | Set the URL and deploy that model's blueprint |
| Frontend deploy: `Publish directory ./out does not exist!` | Service was created as a static site; it is now a web service | Delete the Render service and re-apply `frontend/render.yaml`, Render cannot change service type in place. Re-applying the blueprint alone does **not** work: Render matches by name and will not change an existing service's type |
| `HTTP health check failed (timed out after 5 seconds)` | The agent loop began scraping the instant the port bound and starved `/api/status` | Set `AGENT_LOOP_START_DELAY=45`; if it persists, `DISABLE_AGENT_LOOP=1` |
| Instance restarts in a loop shortly after going live | Same cause, each restart begins another cycle | As above |
| First `/detect` on anomaly hangs for minutes | `ANOMALY_ML_ENABLED=1` with a cold `models_cache/` | Set it back to `0`, or warm the cache (`download_models.py`) before enabling |
| Model service build fails on `requirements.txt` | Wrong file, that is the training set | Dockerfiles must install `requirements-service.txt` |
