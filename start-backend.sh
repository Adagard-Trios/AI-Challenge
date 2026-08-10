#!/usr/bin/env bash
# start-backend.sh
# Run the backend on this machine and publish it at a public HTTPS URL, so the
# Render-hosted frontend can call it.
#
#   ./start-backend.sh --quick      services, backend, throwaway tunnel URL
#   ./start-backend.sh              same, but a NAMED tunnel (needs Cloudflare DNS)
#   ./start-backend.sh --check      validate and exit, start nothing
#   ./start-backend.sh --no-tunnel  services + backend only
#   ./start-backend.sh --no-services   assume postgres/redis are already up
#
# --quick vs named: a named tunnel needs the domain's nameservers to be on
# Cloudflare, because the traffic passes through their edge. nivakaran.dev is
# currently on Spaceship, so `cloudflared tunnel login` shows an empty zone
# list and a named tunnel is not yet possible. --quick needs no account and no
# DNS, at the cost of a hostname that changes on every restart -- and since
# NEXT_PUBLIC_* is baked into the frontend at BUILD time, each new hostname
# means another Render redeploy.
#
# WHY NOT start.sh
# ----------------
# start.sh runs `python main.py`, which binds 0.0.0.0 and skips every
# public-hosting check. This uses backend/scripts/serve_public.py, which binds
# 127.0.0.1 and REFUSES to serve on an unsafe configuration. Loopback is
# correct here: cloudflared runs on this machine and connects outward, so it
# reaches 127.0.0.1 perfectly well -- without also handing the API to every
# other device on the network.
#
# WHY IT PARSES .env INSTEAD OF SOURCING IT
# -----------------------------------------
# `source .env` breaks on this repo's .env for two independent reasons:
#
#   AUTH_SECRET is 62 characters CONTAINING SPACES and unquoted, so bash reads
#   it as an assignment followed by a command and (under `set -e`) start.sh
#   aborts at that line before doing anything at all.
#
#   The file is CRLF, so every sourced value keeps a trailing \r. An invisible
#   \r on CORS_ALLOW_ORIGINS silently stops the frontend origin matching.
#
# THE TUNNEL IS GATED ON AUTH ACTUALLY LOADING
# --------------------------------------------
# main.py catches auth failures with a bare `except Exception` and continues
# with `require_user()` returning None -- every route public, /ws accepting
# unauthenticated connections -- while public_guard, which only reads env
# strings, still reports "All checks passed". Publishing that would put an
# unauthenticated API on the internet.
#
# So this waits for `[auth] ready | enforced=True` in the log and refuses to
# open the tunnel without it.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT/.env"
LOG_DIR="$ROOT/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
TUNNEL_LOG="$LOG_DIR/cloudflared.log"

FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-https://roger.nivakaran.dev}"
PUBLIC_HOST="${PUBLIC_HOST:-api.nivakaran.dev}"
TUNNEL_NAME="${TUNNEL_NAME:-roger-api}"
PORT="${PORT:-8000}"

DO_SERVICES=1; DO_TUNNEL=1; CHECK_ONLY=0; QUICK=0
for arg in "$@"; do
  case "$arg" in
    --check)       CHECK_ONLY=1 ;;
    --quick)       QUICK=1 ;;
    --no-tunnel)   DO_TUNNEL=0 ;;
    --no-services) DO_SERVICES=0 ;;
    -h|--help)     sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mFAILED\033[0m %s\n\n' "$*" >&2; exit 1; }

# Neither Docker Desktop nor cloudflared puts itself on PATH for Git Bash --
# Docker installs per-user, cloudflared lands in Program Files (x86). Both are
# present and both are invisible to `command -v` without this.
export PATH="$PATH:/c/Users/LENOVO/AppData/Local/Programs/DockerDesktop/resources/bin"
export PATH="$PATH:/c/Program Files (x86)/cloudflared"
export PATH="$PATH:/c/Program Files/cloudflared"

# --- .env ------------------------------------------------------------------

[ -f "$ENV_FILE" ] || die ".env not found at $ENV_FILE"

load_env() {
  # Read KEY=VALUE ourselves. Everything after the FIRST '=' is the value,
  # verbatim -- spaces and all -- and a trailing \r is stripped.
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in
      ''|'#'*) continue ;;
      *=*) : ;;
      *) continue ;;
    esac
    local key="${line%%=*}" value="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    [ -n "$key" ] || continue
    export "$key=$value"
  done < "$ENV_FILE"
}

set_env() {
  # Append or replace a key in .env, and export it for this process.
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$ENV_FILE" 2>/dev/null; then
    # Rewrite in place without a temp-file race on Windows.
    python - "$ENV_FILE" "$key" "$value" <<'PY'
import sys, io
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
with io.open(path, encoding="utf-8", errors="surrogateescape") as fh:
    lines = fh.readlines()
out, done = [], False
for line in lines:
    if line.split("=", 1)[0].strip() == key:
        out.append(f"{key}={value}\n"); done = True
    else:
        out.append(line)
if not done:
    out.append(f"{key}={value}\n")
with io.open(path, "w", encoding="utf-8", errors="surrogateescape") as fh:
    fh.writelines(out)
PY
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
  export "$key=$value"
}

load_env

say "Configuration"

[ -n "${GROQ_API_KEY:-}" ] || die "GROQ_API_KEY is not set in .env. The agents cannot classify anything without it."
ok "GROQ_API_KEY present (${#GROQ_API_KEY} chars)"

[ -n "${BOOTSTRAP_ADMIN_EMAIL:-}" ] || die "BOOTSTRAP_ADMIN_EMAIL is unset. With auth on and no admin, nobody can log in."
[ -n "${BOOTSTRAP_ADMIN_PASSWORD:-}" ] || die "BOOTSTRAP_ADMIN_PASSWORD is unset."
[ "${#BOOTSTRAP_ADMIN_PASSWORD}" -ge 10 ] || die "BOOTSTRAP_ADMIN_PASSWORD is ${#BOOTSTRAP_ADMIN_PASSWORD} chars; the seeder requires 10+ and REJECTS SILENTLY, leaving you locked out."
ok "bootstrap admin: $BOOTSTRAP_ADMIN_EMAIL"

# AUTH_SECRET: regenerate a placeholder rather than trusting it. Spaces are the
# tell -- a real token_urlsafe value has none, and the spaces are also what
# breaks `source .env`.
if [ -z "${AUTH_SECRET:-}" ] || [ "${#AUTH_SECRET}" -lt 32 ] || [[ "$AUTH_SECRET" == *" "* ]]; then
  NEW_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  set_env AUTH_SECRET "$NEW_SECRET"
  warn "AUTH_SECRET regenerated (was missing, short, or a phrase with spaces)"
  warn "     every existing session is now invalid -- log in again"
else
  ok "AUTH_SECRET present (${#AUTH_SECRET} chars)"
fi

# PUBLIC_HOSTING is deliberately NOT written to .env.
#
# It describes how THIS process was launched, not a property of the machine.
# Writing it to .env makes every process that loads .env -- including the test
# suite -- claim to be internet-facing, and public_guard then refuses to start
# anything that has not also set AUTH_ENFORCED=1. That is the guard behaving
# correctly against a fact that is not true.
#
# serve_public.py sets it for itself, which is the right scope.
export PUBLIC_HOSTING=1

[ "${AUTH_ENFORCED:-}" = "1" ] || { set_env AUTH_ENFORCED 1; warn "AUTH_ENFORCED set to 1"; }

if [ -z "${CORS_ALLOW_ORIGINS:-}" ]; then
  set_env CORS_ALLOW_ORIGINS "$FRONTEND_ORIGIN"
  warn "CORS_ALLOW_ORIGINS set to $FRONTEND_ORIGIN"
elif [[ ",$CORS_ALLOW_ORIGINS," != *",$FRONTEND_ORIGIN,"* ]]; then
  warn "CORS_ALLOW_ORIGINS does not list $FRONTEND_ORIGIN"
  warn "     the dashboard will fail with an opaque CORS error that names nothing"
fi
ok "CORS: $CORS_ALLOW_ORIGINS"

# DATABASE_URL is MANDATORY once AUTH_ENFORCED=1. Without it auth/config.py
# raises, main.py swallows it, and the API comes up with no authentication at
# all while still claiming to be configured.
if [ -z "${DATABASE_URL:-}" ]; then
  set_env DATABASE_URL "postgresql+psycopg://roger:roger-local-dev@localhost:5432/roger"
  warn "DATABASE_URL set to the local Postgres (mandatory with AUTH_ENFORCED=1)"
fi
ok "database: ${DATABASE_URL%%:*}://... (host: $(printf '%s' "$DATABASE_URL" | sed -E 's#.*@([^/:]+).*#\1#'))"

[ -n "${REDIS_URL:-}" ] || { set_env REDIS_URL "redis://localhost:6379/0"; warn "REDIS_URL set to the local Redis"; }
ok "redis: $REDIS_URL"

if [ -z "${ALLOW_SELF_REGISTRATION:-}" ]; then
  warn "ALLOW_SELF_REGISTRATION is unset and DEFAULTS TO ON"
  warn "     anyone with the URL can create a viewer account and read the feed"
  warn "     (they cannot reach connected social accounts -- those need admin)"
  warn "     set it to 0 in .env to close signups; it is read per request"
fi

if [ "$CHECK_ONLY" = "1" ]; then
  say "Backend validation (serve_public.py --check)"
  (cd "$ROOT/backend" && ./.venv/Scripts/python.exe scripts/serve_public.py --check) || die "the backend refused this configuration"
  say "Check complete -- nothing was started"
  exit 0
fi

# --- data services ---------------------------------------------------------

mkdir -p "$LOG_DIR"

if [ "$DO_SERVICES" = "1" ]; then
  say "Data services"
  command -v docker >/dev/null 2>&1 || die "docker not found. Start Docker Desktop, or pass --no-services."
  docker compose up -d postgres redis chroma minio >/dev/null 2>&1 || die "docker compose failed to start the data services"

  for svc in postgres redis; do
    printf '  waiting for %s' "$svc"
    for _ in $(seq 1 60); do
      state="$(docker inspect --format '{{.State.Health.Status}}' "ai-challenge-${svc}-1" 2>/dev/null || echo unknown)"
      [ "$state" = "healthy" ] && break
      printf '.'; sleep 2
    done
    [ "$state" = "healthy" ] || { printf '\n'; die "$svc did not become healthy; the backend cannot authenticate without it"; }
    printf ' healthy\n'
  done
fi

# --- backend ---------------------------------------------------------------

say "Backend"
[ -x "$ROOT/backend/.venv/Scripts/python.exe" ] || die "backend/.venv not found. Create it and install backend/requirements.txt."

: > "$BACKEND_LOG"
(
  cd "$ROOT/backend" || exit 1
  # serve_public.py sets PUBLIC_HOSTING itself and binds 127.0.0.1.
  exec ./.venv/Scripts/python.exe scripts/serve_public.py --port "$PORT"
) >> "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

cleanup() {
  [ -n "${TUNNEL_PID:-}" ] && kill "$TUNNEL_PID" 2>/dev/null
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null
}
trap cleanup INT TERM

printf '  starting'
AUTH_OK=0
for _ in $(seq 1 90); do
  if grep -q "\[auth\] ready | enforced=True" "$BACKEND_LOG" 2>/dev/null; then
    AUTH_OK=1; break
  fi
  if grep -q "auth layer unavailable" "$BACKEND_LOG" 2>/dev/null; then
    printf '\n'
    grep -m1 -A 3 "auth layer unavailable" "$BACKEND_LOG" | sed 's/^/    /'
    cleanup
    die "the auth layer did not load, so every route would be PUBLIC and /ws would accept
       unauthenticated connections. Refusing to open the tunnel. Usually this means
       Postgres is unreachable -- check DATABASE_URL and that the container is healthy."
  fi
  if grep -qE "Refusing to serve" "$BACKEND_LOG" 2>/dev/null; then
    printf '\n'; sed -n '/Refusing to serve/,$p' "$BACKEND_LOG" | head -20 | sed 's/^/    /'
    cleanup; die "the backend refused this configuration"
  fi
  kill -0 "$BACKEND_PID" 2>/dev/null || { printf '\n'; tail -20 "$BACKEND_LOG" | sed 's/^/    /'; die "the backend exited during startup"; }
  printf '.'; sleep 2
done
printf '\n'

[ "$AUTH_OK" = "1" ] || { cleanup; die "timed out waiting for '[auth] ready | enforced=True' in $BACKEND_LOG"; }
ok "auth is loaded and ENFORCED -- safe to publish"

for _ in $(seq 1 30); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/healthz" 2>/dev/null && break
  sleep 2
done
curl -sf -o /dev/null "http://127.0.0.1:$PORT/healthz" 2>/dev/null \
  && ok "http://127.0.0.1:$PORT/healthz responding" \
  || warn "healthz not responding yet; the tunnel may serve 502 briefly"

# --- tunnel ----------------------------------------------------------------

PUBLIC_URL=""
if [ "$DO_TUNNEL" = "1" ]; then
  say "Cloudflare tunnel"
  if ! command -v cloudflared >/dev/null 2>&1; then
    cleanup
    die "cloudflared not found. Install it:

       winget install --id Cloudflare.cloudflared

     then re-run with --quick. (A NAMED tunnel additionally needs the domain's
     nameservers on Cloudflare; nivakaran.dev is on Spaceship, so its zone list
     is empty and 'cloudflared tunnel login' has nothing to authorise.)"
  fi

  : > "$TUNNEL_LOG"

  if [ "$QUICK" = "1" ]; then
    cloudflared tunnel --url "http://127.0.0.1:$PORT" >> "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    printf '  requesting a hostname'
    for _ in $(seq 1 45); do
      PUBLIC_URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)"
      [ -n "$PUBLIC_URL" ] && break
      kill -0 "$TUNNEL_PID" 2>/dev/null || { printf '\n'; tail -15 "$TUNNEL_LOG" | sed 's/^/    /'; cleanup; die "cloudflared exited"; }
      printf '.'; sleep 2
    done
    printf '\n'
    [ -n "$PUBLIC_URL" ] || { cleanup; die "cloudflared never printed a hostname; see $TUNNEL_LOG"; }
    ok "tunnel up: $PUBLIC_URL"
    warn "this hostname is THROWAWAY -- it changes every restart, and each"
    warn "     change needs a Render redeploy because NEXT_PUBLIC_* is baked in"
  else
    cloudflared tunnel run "$TUNNEL_NAME" >> "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    printf '  connecting'
    for _ in $(seq 1 30); do
      grep -qiE "Registered tunnel connection|Connection [0-9a-f-]+ registered" "$TUNNEL_LOG" 2>/dev/null && break
      kill -0 "$TUNNEL_PID" 2>/dev/null || { printf '\n'; tail -15 "$TUNNEL_LOG" | sed 's/^/    /'; cleanup; die "cloudflared exited. For a named tunnel the zone must be on Cloudflare; try --quick."; }
      printf '.'; sleep 2
    done
    printf '\n'
    PUBLIC_URL="https://$PUBLIC_HOST"
    ok "tunnel up: $PUBLIC_URL"
  fi
fi

# --- ready -----------------------------------------------------------------

say "Running"
SHOW_URL="${PUBLIC_URL:-http://127.0.0.1:$PORT}"
cat <<EOF
  backend    http://127.0.0.1:$PORT        (log: $BACKEND_LOG)
  public     $SHOW_URL
  frontend   $FRONTEND_ORIGIN

  On Render, set BOTH and let it redeploy -- NEXT_PUBLIC_* is inlined at BUILD
  time, so a restart alone keeps the old URL baked into the bundle:

      NEXT_PUBLIC_API_URL  = $SHOW_URL
      NEXT_PUBLIC_API_BASE = $SHOW_URL

  Verify from OUTSIDE this machine (a phone on mobile data is the honest test):

      curl -s $SHOW_URL/healthz                      -> {"ok":true}
      curl -o /dev/null -w '%{http_code}' $SHOW_URL/api/feeds  -> 401

  A 401 there is the point: it proves authentication is genuinely on.

  Ctrl-C stops the backend and the tunnel.
EOF

wait "$BACKEND_PID"
