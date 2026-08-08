#!/usr/bin/env bash
# k8s/deploy-local.sh
# Bring the stack up on a local kind cluster, end to end.
#
# Exists because the deploy is eight steps in a specific order and three of
# them fail silently if skipped: images that are not loaded show as
# ImagePullBackOff (which reads as a network problem), a missing Secret leaves
# pods in CreateContainerConfigError, and a DATABASE_URL pointing at
# "localhost" resolves to the POD, not your machine.
#
#   ./k8s/deploy-local.sh            # build, load, deploy
#   ./k8s/deploy-local.sh --skip-build
set -euo pipefail

CLUSTER="${CLUSTER:-roger}"
NS="${NS:-roger}"
TAG="${TAG:-dev}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The browser talks to the API through a port-forward on the host, so this is a
# host URL. NEXT_PUBLIC_* is inlined at BUILD time -- changing it later means
# rebuilding the image, not restarting the pod.
API_URL="${API_URL:-http://localhost:8000}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

if [[ "${1:-}" != "--skip-build" ]]; then
  say "Building images"
  # Context is the REPO ROOT for the backend: the image needs models/, which is
  # a sibling of backend/.
  docker build -t "roger-backend:$TAG" -f "$REPO_ROOT/backend/Dockerfile" "$REPO_ROOT"
  docker build -t "roger-frontend:$TAG" \
    --build-arg "NEXT_PUBLIC_API_URL=$API_URL" \
    --build-arg "NEXT_PUBLIC_API_BASE=$API_URL" \
    "$REPO_ROOT/frontend"
fi

if ! kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  say "Creating cluster '$CLUSTER'"
  # Two workers so anti-affinity and drain tolerance are real rather than
  # decorative.
  cat <<EOF | kind create cluster --config -
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: $CLUSTER
nodes:
  - role: control-plane
  - role: worker
  - role: worker
EOF
fi

say "Loading images into the cluster"
# kind nodes have their own image store. Without this every pod is
# ImagePullBackOff, trying to pull from a registry that does not have them.
kind load docker-image "roger-backend:$TAG" "roger-frontend:$TAG" --name "$CLUSTER"

say "Namespace and secrets"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# host.docker.internal, NOT localhost: inside a pod, localhost is the POD.
# Redis and Chroma run in-cluster (see k8s/base), so only the database points
# out to the host here.
DB_URL="${DATABASE_URL:-postgresql+psycopg://roger:roger-local-dev@host.docker.internal:5432/roger}"

kubectl -n "$NS" create secret generic roger-secrets \
  --from-literal=GROQ_API_KEY="${GROQ_API_KEY:-}" \
  --from-literal=DATABASE_URL="$DB_URL" \
  --from-literal=AUTH_SECRET="${AUTH_SECRET:-$(head -c 48 /dev/urandom | base64 | tr -d '\n')}" \
  --from-literal=BOOTSTRAP_ADMIN_EMAIL="${BOOTSTRAP_ADMIN_EMAIL:-admin@roger.local}" \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD="${BOOTSTRAP_ADMIN_PASSWORD:-a-long-enough-password}" \
  --dry-run=client -o yaml | kubectl apply -f -

say "Applying k8s/overlays/dev"
kubectl apply -k "$REPO_ROOT/k8s/overlays/dev"

say "Waiting for the dependencies"
kubectl -n "$NS" rollout status statefulset/redis --timeout=180s || true
kubectl -n "$NS" rollout status statefulset/chroma --timeout=300s || true

say "Waiting for the app"
kubectl -n "$NS" rollout status deploy/worker --timeout=420s || true
kubectl -n "$NS" rollout status deploy/api --timeout=420s || true

say "State"
kubectl -n "$NS" get pods -o wide

cat <<'EOF'

Next:
  kubectl -n roger port-forward svc/api 8000:8000
  kubectl -n roger scale deploy/api --replicas=3

  # exactly ONE process should be running graph cycles
  kubectl -n roger logs -l app.kubernetes.io/name=worker --tail=30 | grep -i cycle
  kubectl -n roger logs -l app.kubernetes.io/name=api    --tail=30 | grep -i cycle   # expect nothing
EOF
