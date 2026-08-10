# Kubernetes

## The one thing to understand

Two Deployments from **one image**:

| | replicas | does |
|---|---|---|
| `api` | 2–6 (HPA) | serves HTTP. Collects nothing. |
| `worker` | **1, always** | runs the agent loop and the storage poller |

**Scaling means scaling `api`.** The worker is single-writer by design, for two
reasons that are not going to change:

- Groq's free tier is **8,000 tokens per minute**, and this project already
  hits it at one replica (HTTP 413). A second worker does not double
  throughput, it halves what each gets and fails both.
- Social collection touches **one personal account** behind a 15-minute pacing
  gate and a daily cap. Two workers means two schedules against it.

If collection feels slow, the knob is `AGENT_LOOP_INTERVAL_SECONDS`, never
`worker.replicas`.

## What must exist before this works

The manifests reference a Secret that is deliberately not in git:

```bash
kubectl -n roger create secret generic roger-secrets \
  --from-literal=GROQ_API_KEY=... \
  --from-literal=DATABASE_URL='postgresql+psycopg://user:pass@host:5432/roger' \
  --from-literal=AUTH_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" \
  --from-literal=BOOTSTRAP_ADMIN_EMAIL=you@example.com \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD='at least ten characters'
```

`AUTH_SECRET` must be **one value shared by every pod**. If each minted its own,
a token issued by one replica would be rejected by the next, presenting as
random logouts rather than as a config error. `BOOTSTRAP_ADMIN_PASSWORD` must be
≥10 characters or the seeder rejects it and there is no admin at all.

**Postgres is not in these manifests.** Use a managed one (Supabase/Neon) and
put it in `DATABASE_URL`. An in-cluster StatefulSet on a laptop PVC is a
database whose backup story is "hope". If you use Supabase, use the
**transaction pooler on port 6543**, `auth/db.py` detects it and switches to
`NullPool`, which is the only shape that survives several replicas each holding
a connection pool.

## Deploy (k3d on Windows)

```bash
k3d cluster create roger --agents 2 -p "8080:80@loadbalancer"

docker build -t roger-backend:dev  -f backend/Dockerfile .
docker build -t roger-frontend:dev \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8080 \
  --build-arg NEXT_PUBLIC_API_BASE=http://localhost:8080 ./frontend

k3d image import roger-backend:dev roger-frontend:dev -c roger

kubectl apply -k k8s/overlays/dev
```

`--agents 2` gives genuinely separate nodes, so anti-affinity and drain
tolerance are real rather than decorative.

The frontend URLs are **build args, not env**. Next inlines `NEXT_PUBLIC_*` at
build time; setting them on the pod does nothing, which is the usual reason a
deployed frontend still calls `localhost:8000`.

## Verifying it actually scales

```bash
kubectl -n roger scale deploy/api --replicas=3

# exactly ONE pod should log a cycle
kubectl -n roger logs -l app.kubernetes.io/name=worker --tail=20 | grep CYCLE
kubectl -n roger logs -l app.kubernetes.io/name=api --tail=20 | grep CYCLE   # nothing

# killing an api pod mid-session should be invisible to the browser
kubectl -n roger delete pod -l app.kubernetes.io/name=api --field-selector=…
```

## Probes, do not "simplify" these

`/healthz` and `/readyz` are `async def`. `/api/status` is not, and must never
be probed.

About 47 of `main.py`'s routes are sync `def`, which FastAPI runs in AnyIO's
**40-thread** pool. `rag_chat` blocks on Groq for seconds; `predict_anomaly`
blocks on joblib. Saturate that pool and every sync route queues, including a
sync health check. A liveness probe on a queued endpoint kills a **healthy**
pod, its traffic shifts to the survivors, and they saturate too. Scaling up
causes the outage it was added to prevent, and it presents as *"Kubernetes keeps
restarting my pods under load"*.

The worker deliberately has **no livenessProbe**: a cycle legitimately runs for
minutes, and killing it mid-collection starts another cycle on restart, a crash
loop caused by the probe.

## What does not run here

**Social collection.** `browser_login.py` launches Playwright with
`headless=False` so a human can complete 2FA, and sessions are encrypted to the
OS keyring of the machine that created them. A pod has neither, at any memory
size. Collection runs on the host, shares the same Redis pacing gate and the
same Postgres, and the cluster sets `DISABLE_LOCAL_SOCIAL_SESSIONS=1`.

The clean framing: **the cluster is the read and reasoning path; the host is the
credentialed write path.** The internet-facing half holds no credentials.

## Honest limits

- One machine. Three api pods share one CPU and one uplink, this buys
  **concurrency and isolation, not throughput**.
- Chroma is a single node. It replaces N divergent per-pod corpora with one
  correct shared one, which is the point, but it is a shared service rather
  than a scaled one and a new single point of failure for the read path.
- Availability is capped by the laptop. `replicas: 3` and a PDB read as high
  availability; closing the lid takes down all three.
