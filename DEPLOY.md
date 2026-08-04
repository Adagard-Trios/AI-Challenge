# Deploying — Render (+ Vercel option for the frontend)

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
- *Deployed* the image installs the slim `requirements-service.txt`, which has no ML framework —
  so each model must have its `*_SERVICE_URL` pointing at its own service. Without one, that
  model's endpoints return the gateway's "unavailable" response. See §1.2.

Deploy order: **model services → backend → frontend.** Each step needs the previous URL.

> Splitting the models out also removes the reason for `main.py`'s `sys.path`/`sys.modules` surgery:
> all four projects define a top-level package named `src`, which cannot coexist in one interpreter
> but is a non-issue once each runs in its own container.

---

## 0. Model services (optional, deploy first)

Each model folder is self-contained: `service.py` (FastAPI), `Dockerfile`, `requirements-service.txt`
(serving deps only — no mlflow/optuna/dagshub), and `render.yaml`.

Apply each blueprint separately: **New → Blueprint →** this repo → point at that model's
`render.yaml`. `rootDir` scopes the build context to the model folder.

| Service | Endpoints | Plan | Notes |
|---|---|---|---|
| `slac2026-weather` | `/health` `/model/status` `/predict` `/predict/{district}` | free | TensorFlow — **tight on 512 MB** |
| `slac2026-currency` | `/health` `/model/status` `/predict` | free | TensorFlow — **tight on 512 MB** |
| `slac2026-stock` | `/health` `/model/status` `/predict` `/predict/{symbol}` | free | no TensorFlow — the one that fits comfortably |
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
- **Anomaly**: embedding-based scoring is **opt-in** via `ANOMALY_ML_ENABLED=1`. Left off, the
  service uses the same keyword/severity heuristic the monolith falls back to, and responds in
  ~50 ms. Turned on with a cold `models_cache/`, the first `/detect` blocks for minutes downloading
  BERT weights — so enable it only after confirming the cache is warm via `/model/status`.

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

Verify the wiring with **`GET /api/status`** and **`GET /api/models/health`** — the latter reports
`mode: in-process | remote` and reachability per model.

### 1.1 Why Docker and not a Python service

The app needs Playwright + Chromium and its system libraries for the scrapers. Render's native
Python runtime can't install those. `backend/Dockerfile` already handles it.

### 1.2 Two requirement sets — this is what fixes the OOM

| File | Used by | Contents |
|---|---|---|
| `requirements.txt` | local dev | Full set, **3.12 GB installed** — includes TensorFlow, PyTorch and the training stack so models can run **in-process** |
| `requirements-service.txt` | `backend/Dockerfile` | Slim runtime set — no TensorFlow, PyTorch, sklearn, mlflow or training deps |

The deployed backend does not need any ML framework: the four models run as their own services and
the backend calls them over HTTP via `src/model_gateway.py`.

**The subtle part.** The backend has *no module-level import* of torch or tensorflow anywhere.
But `langchain_groq.chat_models` imports `transformers` **if it happens to be installed**, and
`transformers` then imports `torch` — roughly 3 GB of resident stack pulled in by accident, purely
because the packages were present. Verified by blocking both modules: `from langchain_groq import
ChatGroq` and `ChatGroq(...)` still work. Not installing them removes the import entirely.

ChromaDB is unaffected — `chromadb_store.py` passes `CHROMADB_EMBEDDING_MODEL` as collection
*metadata* only, so Chroma uses its bundled ONNX embedder, not sentence-transformers.

**Consequence:** with the slim set, the in-process fallback cannot work. Every model endpoint needs
its `<MODEL>_SERVICE_URL` set, or the gateway returns its unavailable response. That is the intended
deployed topology — deploy the four model blueprints first.

### 1.3 Deploy

**Blueprint (recommended)** — Dashboard → **New** → **Blueprint** → select this repo. It reads
`render.yaml` and provisions the service and env-var slots.

**Manual** — New → Web Service → Docker, then set:

| Setting | Value |
|---|---|
| Dockerfile Path | `./backend/Dockerfile` |
| Docker Build Context | `.` (**repo root — not `backend/`**) |
| Health Check Path | `/api/status` |
| Disk | none — free tier does not support persistent disks |

The build context **must** be the repo root: the image needs `models/`, which is a sibling of
`backend/`, because `main.py` resolves it as `Path(__file__).parent.parent / "models"`.

### 1.4 Environment variables

Set in the Render dashboard (the `sync: false` entries in `render.yaml` are deliberately blank):

| Variable | Value | Required |
|---|---|---|
| `GROQ_API_KEY` | your Groq key | **Yes** — the app raises at import without it |
| `DISABLE_AUTO_TRAIN` | `1` | **Yes** — see below |
| `CORS_ALLOW_ORIGINS` | frontend origin, e.g. `https://slac2026-frontend.onrender.com` | Strongly recommended |
| `SQLITE_DB_PATH` | `/app/backend/data/cache/feeds.db` | Pre-set in `render.yaml` |
| `CHROMADB_PATH` | `/app/backend/data/chromadb` | Pre-set |
| `CSV_EXPORT_DIR` | `/app/backend/data/feeds` | Pre-set |
| `NEO4J_ENABLED` | `false` | Pre-set |
| `LANGSMITH_API_KEY` | optional tracing | No |

Do **not** set `PORT` — Render injects it, and `start_backend.sh` already binds `0.0.0.0:$PORT`.

### 1.5 Why `DISABLE_AUTO_TRAIN=1` is mandatory

`main.py` calls `check_and_train_models()` at *import*, which forks ML training subprocesses with a
30-minute timeout. On Render that runs on every cold start and will OOM the instance before it can
bind `$PORT`. The gate makes it a no-op. Trained artifacts are already committed under
`models/*/artifacts/`, so nothing is lost.

Retrain locally or via the Airflow DAGs in `airflow/`, then commit the updated artifacts.

### 1.6 Storage is ephemeral on the free plan

`backend/data/` holds the SQLite dedup cache and the ChromaDB vector store. **Render's filesystem is
ephemeral, and the free plan cannot mount a persistent disk** — so every deploy, restart and
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
deploys**. Acceptable here — the app runs a singleton 60s agent loop and isn't horizontally
scalable anyway.

### 1.7 First boot expectations

Cold start is slow — TensorFlow/PyTorch import plus graph compilation. Expect **2–5 minutes** before
`/api/status` answers. Give the health check a generous grace period.

Startup log should show:

```
[STARTUP] Auto-training disabled (DISABLE_AUTO_TRAIN set)
[STARTUP] CORS origins: ['https://<your-app>.vercel.app'] (credentials=on)
[SQLiteCache] Initialized at /app/backend/data/cache/feeds.db
[ChromaDB] Initialized collection: Roger_feeds
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
server-side features stay available — API routes, server actions, SSR, middleware — even though the
current dashboard renders client-side.

Pick **one** host.

### 2A. Render — Node web service

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

Connect Vercel directly to this repo — it builds `frontend/` in place, and its Git integration
handles push-to-deploy (there is no CI step for the frontend, and none is needed).

| Setting | Value |
|---|---|
| **Root Directory** | `frontend` ← **required**, this is a monorepo |
| Framework Preset | Next.js (auto-detected) |
| Install Command | `npm ci` (already in `frontend/vercel.json`) |

**Do not change the install command back to `npm install`.** Four packages — `clsx`,
`@radix-ui/react-slot`, `@radix-ui/react-dialog`, `@radix-ui/react-collapsible` — are imported by the
UI but *not declared* in `package.json`. They resolve only as hoisted transitives from the committed
lockfile. `npm install` may re-resolve and fail the build.

### 2C. Environment variables — set **both** (either host)

The codebase reads two different names: 8 files use `NEXT_PUBLIC_API_URL`, but
`app/components/dashboard/AnomalyDetection.tsx` and `app/components/dashboard/StockPredictions.tsx`
use `NEXT_PUBLIC_API_BASE`. Set **both to the same value** or those two panels will silently fall
back to `http://localhost:8000` in production:

```
NEXT_PUBLIC_API_URL  = https://<service>.onrender.com
NEXT_PUBLIC_API_BASE = https://<service>.onrender.com
```

No trailing slash. These are inlined at build time — **changing them requires a redeploy**, not just
a restart.

### 2D. WebSocket

`use-roger-data.ts` derives the socket URL as `API_BASE.replace('http','ws') + '/ws'`, so an
`https://` backend correctly becomes `wss://…/ws`. The socket is opened by the browser straight to
the backend, so it never traverses the frontend server — the choice of host is irrelevant to it.

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
7. Open the Vercel URL — the dashboard should populate within ~2 minutes of the backend's agent loop.

### Plan note

**All five blueprints ship with `plan: free`.** That costs nothing, and it comes with three
constraints worth knowing before you debug a "broken" deploy:

| Constraint | Effect |
|---|---|
| 512 MB RAM | The backend (3.12 GB of deps) is expected to OOM during import. Weather and currency are borderline once TensorFlow loads. Stock and anomaly (heuristic tier) are fine. |
| No persistent disks | Free plans cannot mount one. SQLite/ChromaDB state and generated predictions are wiped on every restart. |
| Spin-down after ~15 min idle | The next request pays a full cold start — minutes for the TensorFlow/PyTorch services. |

Realistically: **stock and anomaly run well on free**; weather and currency will be flaky; the
backend needs `standard` (2 GB) to stay up. Raise `plan:` per service as needed — they are
independent, so you can pay for only the backend and leave the four model services free.

Remember the model services are opt-in: leaving all four `*_SERVICE_URL` vars unset runs every
model in-process and costs exactly one service.

---

## 4. Security

- **`backend/src/utils/.sessions/*.json` contains live session cookies** for real Facebook,
  Instagram, LinkedIn, Reddit and X accounts. They are committed to the repo *and* baked into the
  Docker image (deliberately — the scrapers need them for authenticated access). Anyone with repo or
  image access can hijack those sessions. Rotate them if this repo is or becomes public.
- `CORS_ALLOW_ORIGINS` defaults to `*`. When it is `*`, credentials are automatically disabled
  (the CORS spec forbids that combination and browsers reject it). Set a real origin in production.
- `GROQ_API_KEY` must only ever come from the Render dashboard — never commit it. `.env` is
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
| All feeds vanish after a deploy | Free tier has no persistent disk — expected | Move to a paid plan and attach a disk at `/app/backend/data` |
| Anomaly + Stock panels empty, rest fine | Only one env-var name set | Set `NEXT_PUBLIC_API_BASE` too (§2.2) |
| Browser console: CORS error | Origin not allowlisted | Set `CORS_ALLOW_ORIGINS` to the exact Vercel origin, no trailing slash |
| Vercel build: "Module not found: clsx" | `npm install` re-resolved deps | Restore `npm ci` |
| `[MODEL CHECK] ⚠ Anomaly Detection - No model found` | Pre-existing upstream quirk — `main.py` checks `artifacts/models`, files are in `artifacts/model_trainer/` | Harmless with `DISABLE_AUTO_TRAIN=1`; anomaly endpoints degrade gracefully |
| `/api/models/health` shows `in-process` when you expected `remote` | `*_SERVICE_URL` unset or empty on the backend | Set it, then redeploy the backend |
| Model endpoints answer but ignore the model service | Service unreachable — gateway fell back silently | Check backend logs for `[gateway] … call failed`; hit the service's `/health` directly |
| Model endpoints return "unavailable" | `<MODEL>_SERVICE_URL` unset, and the slim image has no ML framework for the in-process path | Set the URL and deploy that model's blueprint |
| Frontend deploy: `Publish directory ./out does not exist!` | Service was created as a static site; it is now a web service | Delete the Render service and re-apply `frontend/render.yaml` — Render cannot change service type in place |
| First `/detect` on anomaly hangs for minutes | `ANOMALY_ML_ENABLED=1` with a cold `models_cache/` | Set it back to `0`, or warm the cache (`download_models.py`) before enabling |
| Model service build fails on `requirements.txt` | Wrong file — that is the training set | Dockerfiles must install `requirements-service.txt` |
