# Deploying — Render + Vercel

Six deployables, each with its own blueprint:

| # | Service | Source | Blueprint | Platform |
|---|---|---|---|---|
| 1 | Backend API | `backend/` | `render.yaml` | Render (Docker) |
| 2 | Weather model | `models/weather-prediction/` | `models/weather-prediction/render.yaml` | Render (Docker) |
| 3 | Currency model | `models/currency-volatility-prediction/` | same folder | Render (Docker) |
| 4 | Stock model | `models/stock-price-prediction/` | same folder | Render (Docker) |
| 5 | Anomaly model | `models/anomaly-detection/` | same folder | Render (Docker) |
| 6 | Frontend | `frontend/` | — | Vercel |

**The model services are optional.** The backend runs all four models in-process by default, exactly
as before. It only calls a model over HTTP when that model's `*_SERVICE_URL` is set — and if the
call fails it silently falls back to in-process. So you can deploy just #1 and #6, then peel models
off one at a time.

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
| `slac2026-weather` | `/health` `/model/status` `/predict` `/predict/{district}` | standard | TensorFlow |
| `slac2026-currency` | `/health` `/model/status` `/predict` | standard | TensorFlow |
| `slac2026-stock` | `/health` `/model/status` `/predict` `/predict/{symbol}` | **starter** | no TensorFlow — unpickles via scikit-learn |
| `slac2026-anomaly` | `/health` `/model/status` `POST /detect` | standard | PyTorch + BERT |

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

---

## 1. Backend → Render

### 1.1 Why Docker and not a Python service

The app needs Playwright + Chromium and its system libraries for the scrapers. Render's native
Python runtime can't install those. `backend/Dockerfile` already handles it.

### 1.2 Plan sizing — read this before picking

Importing `main.py` loads TensorFlow, PyTorch, ChromaDB, sentence-transformers and six LangGraph
agents into one process. Measured install size is **3.12 GB** (TensorFlow 1.3 GB, PyTorch 414 MB).

| Plan | RAM | Verdict |
|---|---|---|
| Free / Starter | 512 MB | **Will not work** — OOMs during import, and Free spins down on idle (cold start is minutes) |
| **Standard** | 2 GB | Minimum viable; expect tight headroom |
| **Pro** | 4 GB | Recommended if the service gets OOM-killed under load |

`render.yaml` ships with `plan: standard`. Bump to `pro` there if you see OOM restarts.

### 1.3 Deploy

**Blueprint (recommended)** — Dashboard → **New** → **Blueprint** → select this repo. It reads
`render.yaml` and provisions the service, disk and env-var slots.

**Manual** — New → Web Service → Docker, then set:

| Setting | Value |
|---|---|
| Dockerfile Path | `./backend/Dockerfile` |
| Docker Build Context | `.` (**repo root — not `backend/`**) |
| Health Check Path | `/api/status` |
| Disk mount path | `/app/backend/data` (10 GB) |

The build context **must** be the repo root: the image needs `models/`, which is a sibling of
`backend/`, because `main.py` resolves it as `Path(__file__).parent.parent / "models"`.

### 1.4 Environment variables

Set in the Render dashboard (the `sync: false` entries in `render.yaml` are deliberately blank):

| Variable | Value | Required |
|---|---|---|
| `GROQ_API_KEY` | your Groq key | **Yes** — the app raises at import without it |
| `DISABLE_AUTO_TRAIN` | `1` | **Yes** — see below |
| `CORS_ALLOW_ORIGINS` | `https://<your-app>.vercel.app` | Strongly recommended |
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

### 1.6 Persistent disk

`backend/data/` holds the SQLite dedup cache and the ChromaDB vector store. **Render's filesystem is
ephemeral** — without the disk, every deploy and restart wipes all collected intelligence and the
dedup layer starts from zero.

Trade-off: attaching a disk pins the service to **one instance** and **disables zero-downtime
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

## 2. Frontend → Vercel

### 2.1 Project settings

| Setting | Value |
|---|---|
| **Root Directory** | `frontend` ← **required**, this is a monorepo |
| Framework Preset | Next.js (auto-detected) |
| Install Command | `npm ci` (already in `frontend/vercel.json`) |

**Do not change the install command back to `npm install`.** Four packages — `clsx`,
`@radix-ui/react-slot`, `@radix-ui/react-dialog`, `@radix-ui/react-collapsible` — are imported by the
UI but *not declared* in `package.json`. They resolve only as hoisted transitives from the committed
lockfile. `npm install` may re-resolve and fail the build.

### 2.2 Environment variables — set **both**

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

### 2.3 WebSocket

`use-roger-data.ts` derives the socket URL as `API_BASE.replace('http','ws') + '/ws'`, so an
`https://` backend correctly becomes `wss://…/ws`. Render supports WebSockets on paid plans; no
extra configuration needed.

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

### Cost note

Five Render services is real money. Only the backend is mandatory; each model service is opt-in and
independently removable. The blueprints ship with `standard` (2 GB) for the three heavy models and
`starter` (512 MB) for stock. Dropping all four model services and running everything in-process —
the default — costs one service.

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
| Service restarts in a loop, "Out of memory" | Plan too small, or auto-train ran | Set `DISABLE_AUTO_TRAIN=1`; upgrade to `pro` |
| Health check never passes | Cold start slower than the window | Raise the grace period; confirm `$PORT` is not overridden |
| All feeds vanish after a deploy | No persistent disk | Attach the disk at `/app/backend/data` |
| Anomaly + Stock panels empty, rest fine | Only one env-var name set | Set `NEXT_PUBLIC_API_BASE` too (§2.2) |
| Browser console: CORS error | Origin not allowlisted | Set `CORS_ALLOW_ORIGINS` to the exact Vercel origin, no trailing slash |
| Vercel build: "Module not found: clsx" | `npm install` re-resolved deps | Restore `npm ci` |
| `[MODEL CHECK] ⚠ Anomaly Detection - No model found` | Pre-existing upstream quirk — `main.py` checks `artifacts/models`, files are in `artifacts/model_trainer/` | Harmless with `DISABLE_AUTO_TRAIN=1`; anomaly endpoints degrade gracefully |
| `/api/models/health` shows `in-process` when you expected `remote` | `*_SERVICE_URL` unset or empty on the backend | Set it, then redeploy the backend |
| Model endpoints answer but ignore the model service | Service unreachable — gateway fell back silently | Check backend logs for `[gateway] … call failed`; hit the service's `/health` directly |
| First `/detect` on anomaly hangs for minutes | `ANOMALY_ML_ENABLED=1` with a cold `models_cache/` | Set it back to `0`, or warm the cache (`download_models.py`) before enabling |
| Model service build fails on `requirements.txt` | Wrong file — that is the training set | Dockerfiles must install `requirements-service.txt` |
