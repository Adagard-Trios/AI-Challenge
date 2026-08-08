"""
The Kubernetes manifests, asserted rather than trusted.

Manifests are the easy day; the invariants below are the ones that stop a
scaling change from becoming an incident, and every one of them is a single
line somebody could "tidy up" without knowing what it defends.

Three matter more than the rest:

  worker replicas: 1        two workers means two agent cycles against a Groq
                            allowance already at its 8,000 tokens/minute
                            ceiling at ONE, and two collection schedules
                            against a single personal social account.

  worker Recreate           the default RollingUpdate surges a second pod
                            before terminating the first, so every rollout
                            briefly runs two workers -- the situation above,
                            for the length of a deploy.

  probes are async          ~47 of main.py's routes are sync def and run in
                            AnyIO's 40-thread pool. A liveness probe that can
                            queue behind them kills HEALTHY pods under load and
                            cascades.

Parsed as YAML rather than grepped, so a comment mentioning "replicas: 2"
cannot pass or fail a test about replicas.
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parent.parent.parent.parent
BASE = REPO / "k8s" / "base"


def _load_all():
    """Every manifest under k8s/base, as parsed documents."""
    if not BASE.is_dir():
        pytest.skip("k8s/base not present")
    docs = []
    for path in sorted(BASE.rglob("*.yaml")):
        if path.name == "kustomization.yaml":
            continue
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if doc:
                docs.append(doc)
    return docs


def _by(kind, name):
    return next(
        (d for d in _load_all()
         if d.get("kind") == kind and d.get("metadata", {}).get("name") == name),
        None,
    )


def _container(deployment):
    return deployment["spec"]["template"]["spec"]["containers"][0]


def _env(deployment):
    return {e["name"]: e.get("value")
            for e in _container(deployment).get("env", [])}


# --- the worker is a singleton ----------------------------------------------

def test_the_worker_runs_exactly_one_replica():
    worker = _by("Deployment", "worker")
    assert worker is not None, "no worker Deployment"
    assert worker["spec"]["replicas"] == 1, (
        "more than one worker means two agent cycles against a Groq allowance "
        "already at its ceiling at one, and two collection schedules against "
        "a single personal social account"
    )


def test_the_worker_never_surges_a_second_pod_during_a_rollout():
    """
    RollingUpdate is the DEFAULT, so this is a thing that must be present
    rather than a thing that must be absent -- the failure mode is forgetting
    to write it, not writing it wrongly.
    """
    worker = _by("Deployment", "worker")
    assert worker["spec"].get("strategy", {}).get("type") == "Recreate", (
        "the worker uses RollingUpdate, so every deploy briefly runs two "
        "workers"
    )


def test_only_the_worker_collects_and_only_the_api_serves():
    assert _env(_by("Deployment", "worker")) == {
        "ROLE": "worker", "DISABLE_AGENT_LOOP": "0"}
    api = _env(_by("Deployment", "api"))
    assert api.get("ROLE") == "api"
    assert api.get("DISABLE_AGENT_LOOP") == "1", (
        "api pods would run their own agent loop"
    )


def test_the_worker_has_no_liveness_probe():
    """
    A cycle legitimately runs for minutes -- five agents, gazette PDFs, LLM
    calls. Liveness would kill a working process mid-collection, and the
    restart begins another cycle: a crash loop caused by the probe. This is
    the failure that killed the Render instance before AGENT_LOOP_START_DELAY
    existed.
    """
    assert "livenessProbe" not in _container(_by("Deployment", "worker"))


def test_the_worker_has_no_pod_disruption_budget():
    """
    replicas:1 plus minAvailable:1 means the eviction API can never remove the
    pod, so `kubectl drain` blocks forever and node maintenance deadlocks.
    """
    for doc in _load_all():
        if doc.get("kind") != "PodDisruptionBudget":
            continue
        selector = doc["spec"]["selector"]["matchLabels"]
        assert selector.get("app.kubernetes.io/name") != "worker", (
            "a PDB on a single-replica worker makes the node undrainable"
        )


# --- probes -----------------------------------------------------------------

@pytest.mark.parametrize("name", ["api", "worker"])
def test_probes_never_point_at_api_status(name):
    """
    /api/status is a sync def that does real work. Probing it is the trap:
    under load it queues behind the threadpool and the orchestrator kills
    healthy pods.
    """
    container = _container(_by("Deployment", name))
    for probe in ("livenessProbe", "readinessProbe", "startupProbe"):
        spec = container.get(probe)
        if not spec or "httpGet" not in spec:
            continue
        assert spec["httpGet"]["path"] in ("/healthz", "/readyz"), (
            f"{name}.{probe} points at {spec['httpGet']['path']}, which is not "
            f"one of the async probe endpoints"
        )


def test_the_api_startup_probe_allows_a_slow_import():
    """
    `import main` builds ~74 routes and warms the ONNX embedder. A tight
    startup budget restarts a pod that is merely booting, forever.
    """
    probe = _container(_by("Deployment", "api"))["startupProbe"]
    budget = probe["periodSeconds"] * probe["failureThreshold"]
    assert budget >= 120, f"only {budget}s to start; the import alone can exceed it"


# --- autoscaling ------------------------------------------------------------

def test_the_api_declares_cpu_requests_or_the_hpa_is_decorative():
    """
    The HPA computes utilisation against requests. Without requests.cpu it
    reports <unknown>/70% and never scales -- an autoscaler that looks
    configured and does nothing.
    """
    requests = _container(_by("Deployment", "api"))["resources"]["requests"]
    assert requests.get("cpu"), "api has no cpu request; the HPA cannot scale it"


def test_nothing_scales_the_worker():
    for doc in _load_all():
        if doc.get("kind") != "HorizontalPodAutoscaler":
            continue
        assert doc["spec"]["scaleTargetRef"]["name"] != "worker", (
            "an HPA on the worker would create the concurrency the whole "
            "topology exists to prevent"
        )


# --- configuration ----------------------------------------------------------

def test_self_registration_is_closed_by_default():
    """
    The code default is ON. On a public URL that means anyone with the link
    can create an account and read the intelligence feed.
    """
    config = _by("ConfigMap", "roger-config")["data"]
    assert config.get("ALLOW_SELF_REGISTRATION") == "0"
    assert config.get("AUTH_ENFORCED") == "1"


def test_the_agent_interval_is_slower_than_the_code_default():
    """
    Groq's free tier is 8,000 tokens/minute and this project hits it at one
    replica. Replicas add no tokens; the interval is the only knob that helps.
    """
    config = _by("ConfigMap", "roger-config")["data"]
    assert int(config["AGENT_LOOP_INTERVAL_SECONDS"]) >= 120


def test_social_sessions_are_disabled_in_cluster():
    """
    Connecting an account opens a VISIBLE browser for 2FA and encrypts the
    session to the host's OS keyring. A pod has neither, at any memory size.
    """
    config = _by("ConfigMap", "roger-config")["data"]
    assert config.get("DISABLE_LOCAL_SOCIAL_SESSIONS") == "1"


def test_the_frontend_carries_no_next_public_env():
    """
    Next inlines NEXT_PUBLIC_* at BUILD time. Setting them on the pod does
    nothing, and looks like it should work -- which is how this frontend ends
    up deployed still calling localhost:8000.
    """
    env = _env(_by("Deployment", "frontend"))
    leaked = [k for k in env if k.startswith("NEXT_PUBLIC_")]
    assert not leaked, f"{leaked} set as pod env; they are build args"
