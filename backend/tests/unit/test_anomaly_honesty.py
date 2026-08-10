"""
Anomaly detection must never report a score it did not compute.

THE BUG THIS LOCKS DOWN
-----------------------
models/anomaly-detection/src/utils/vectorizer.py embeds text with distilBERT
via transformers + torch. Neither is installed in the deployed image -- they
are ~3 GB and OOM a 512 MB instance. The vectorizer does not raise when they
are missing; it logs and returns np.zeros(768).

A fitted isolation forest accepts a zero vector perfectly happily. Measured,
with transformers and torch blocked exactly as the deployed image has them:

    nonzero_dims=0  pred=-1  score=+0.012138   Heavy flooding in Ratnapura...
    nonzero_dims=0  pred=-1  score=+0.012138   Colombo Port operating normally...
    nonzero_dims=0  pred=-1  score=+0.012138   Central Bank holds rate steady...

Every event identical, every event anomalous, and /api/anomalies reporting
model_status "ml_active" the whole time. Nothing errors, nothing logs at
WARNING, and the number on the dashboard is fiction.

That is worse than an outage, because an outage is visible. These tests exist
so it cannot come back.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPO_ROOT = PROJECT_ROOT.parent
for path in (str(PROJECT_ROOT), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


def _source_of(function: str) -> str:
    """
    A function's source, read from main.py rather than imported.

    Deliberately not `import main`. main.py bootstraps the auth layer on
    import, and tests/unit/test_auth_e2e.py sets DATABASE_URL in a module
    fixture and *then* imports main -- so whichever module imports it first
    decides which database the auth layer binds to. Importing it here made ten
    auth tests fail with "no such table: users" purely by running earlier in
    the alphabet.

    Reading the source keeps these tests to what they are actually asserting
    (the shape of the code) with no import side effects at all.
    """
    import ast

    tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            return ast.get_source_segment(
                (PROJECT_ROOT / "main.py").read_text(encoding="utf-8"), node
            ) or ""
    raise AssertionError(f"main.py has no function named {function!r}")


# --- the embedder refuses rather than returning zeros ----------------------

def test_embed_raises_instead_of_returning_a_zero_vector():
    """
    The single most important property here.

    A zero vector is a *valid input* to a fitted model, so returning one buys a
    confident answer about nothing. An exception buys a fallback that says what
    it is.
    """
    from src import embeddings

    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed([])
    with pytest.raises(embeddings.EmbeddingUnavailable):
        embeddings.embed(["", "   "])


def test_embeddings_are_real_and_differ_between_texts():
    from src import embeddings

    if not embeddings.available():
        pytest.skip("ONNX embedder not downloaded in this environment")

    a, b = embeddings.embed([
        "Heavy flooding in Ratnapura with evacuations underway.",
        "Central Bank holds the policy rate steady at 8 percent.",
    ])

    assert len(a) == embeddings.EMBEDDING_DIM
    assert any(v != 0.0 for v in a), "embedding is all zeros"
    assert a != b, "two unrelated sentences produced identical embeddings"


# --- the production image must not use the 768-dim path --------------------

def test_bert_path_is_gated_on_transformers_actually_being_installed():
    """
    The guard that stops the zeros from ever being scored.

    Checked by import presence rather than by attempting a vectorisation,
    because attempting it *succeeds* -- returning zeros -- which is exactly why
    the original code could not tell the difference.
    """
    source = _source_of("_bert_vectorizer_usable")
    assert "transformers" in source and "torch" in source

    loader = _source_of("_load_anomaly_components")
    assert "_bert_vectorizer_usable()" in loader, (
        "the 768-dim models are loaded without checking that their vectorizer "
        "can produce real vectors"
    )


def test_the_deployed_requirements_do_not_install_the_768_dim_stack():
    """
    If transformers/torch ever land in the slim set, the memory budget is gone
    and the reasoning in this module needs revisiting.
    """
    text = (PROJECT_ROOT / "requirements-service.txt").read_text(encoding="utf-8")
    lines = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    for banned in ("torch", "transformers", "tensorflow", "sentence-transformers"):
        assert not any(line.split("=")[0].split(">")[0].strip() == banned for line in lines), (
            f"{banned} is in the deployed requirement set"
        )


def test_the_deployed_requirements_do_install_what_anomaly_detection_needs():
    text = (PROJECT_ROOT / "requirements-service.txt").read_text(encoding="utf-8")
    lines = [
        line.strip().split("=")[0].split(">")[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # sklearn to run the forest, chromadb for the ONNX embedder it is fitted on.
    assert "scikit-learn" in lines
    assert "chromadb" in lines


# --- the endpoints label what they are doing -------------------------------

def test_heuristic_scoring_never_claims_to_be_a_model():
    """
    The fallback is fine. Presenting it as ML is not -- the distinction is the
    difference between a demo and a misrepresentation.
    """
    source = _source_of("get_anomalies")
    fallback = source.split("fallback_scoring")[1][:400]

    assert '"is_ml": False' in fallback or "'is_ml': False" in fallback, (
        "the heuristic branch does not mark itself as non-ML"
    )
    assert "heuristic" in fallback.lower()


def test_a_scoring_failure_does_not_degrade_to_zero_scores():
    """
    An anomaly_score of 0.0 reads as "confidently normal", so it is the worst
    possible value to emit when scoring failed.
    """
    for name in ("get_anomalies", "predict_anomaly"):
        assert '"model_status": "error"' in _source_of(name), (
            f"{name} has no explicit error status; a failure would be "
            "reported as a successful score"
        )


def test_both_endpoints_share_one_scoring_path():
    """They drifted apart once already; a shared helper is what stops it."""
    for name in ("get_anomalies", "predict_anomaly"):
        assert "_score_texts(" in _source_of(name)


# --- the training script refuses to ship a model that does not generalise ---

def test_training_aborts_when_the_model_flags_everything():
    """
    The first fit of this script trained on 3,449 mostly-gazette chunks and
    flagged 6 of 7 ordinary news sentences while looking healthy on every
    training-set measure. Held-out validation is what caught it.
    """
    source = (PROJECT_ROOT / "scripts" / "train_anomaly_minilm.py").read_text(encoding="utf-8")

    assert "held" in source.lower(), "no held-out validation"
    assert "ABORT" in source, "nothing stops a degenerate model being written"
    assert "CONTAMINATION * 3" in source, "no bound on the held-out flag rate"


def test_training_scores_the_same_field_it_trains_on():
    """
    Runtime scores `summary` (median ~159 chars). The vector store also holds
    3,503 raw source chunks (median ~968). Training on those is training on a
    different distribution than the one being scored.
    """
    source = (PROJECT_ROOT / "scripts" / "train_anomaly_minilm.py").read_text(encoding="utf-8")

    assert "MAX_CHARS" in source, "no upper bound; raw document chunks would be included"
    assert "summary" in source


# --- the model on disk matches the embedder that will feed it --------------

def test_the_committed_model_expects_the_embedding_width_we_produce():
    """
    A mismatch here is the good kind of failure -- sklearn raises on the
    feature count rather than scoring silently -- but it means anomaly
    detection is down, so catch it in CI instead.
    """
    joblib = pytest.importorskip("joblib")
    pytest.importorskip("sklearn")

    from src import embeddings

    path = (
        REPO_ROOT / "models" / "anomaly-detection" / "artifacts"
        / "model_trainer" / "isolation_forest_minilm.joblib"
    )
    if not path.exists():
        pytest.skip("MiniLM model not built; run scripts/train_anomaly_minilm.py")

    model = joblib.load(path)
    assert model.n_features_in_ == embeddings.EMBEDDING_DIM


def test_the_shipped_model_is_not_gitignored():
    """
    Render builds from the git repo, so an ignored artifact does not exist in
    production -- and anomaly detection would fall back to heuristic scoring
    there while working perfectly on the machine that trained it.

    This nearly happened: `**/Artifacts/` in .gitignore matched
    `models/anomaly-detection/artifacts/` because git on Windows compares
    ignore patterns case-insensitively. The older .joblib files survived only
    because they were force-added before that rule existed.
    """
    import subprocess

    path = (
        REPO_ROOT / "models" / "anomaly-detection" / "artifacts"
        / "model_trainer" / "isolation_forest_minilm.joblib"
    )
    if not path.exists():
        pytest.skip("MiniLM model not built; run scripts/train_anomaly_minilm.py")

    result = subprocess.run(
        ["git", "check-ignore", str(path.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    # check-ignore exits 0 when a rule matched (i.e. the file IS ignored),
    # 1 when nothing matched.
    assert result.returncode != 0, (
        f"the shipped anomaly model is gitignored by: {result.stdout.strip()}\n"
        "It will not reach the deployed image, and /api/anomalies will silently "
        "degrade to heuristic scoring in production."
    )


def test_training_intermediates_stay_ignored():
    """
    The counterpart. Loosening the ignore rule to let the model through must
    not start committing regenerable parquet dumps.
    """
    import subprocess

    for stage in ("data_ingestion", "data_validation",
                  "data_transformation", "model_evaluation"):
        rel = f"models/anomaly-detection/artifacts/{stage}/sample.parquet"
        result = subprocess.run(
            ["git", "check-ignore", rel],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"{stage} intermediates are no longer ignored"


def test_the_model_produces_varying_scores():
    """The regression test for the constant-score bug, on the real artifact."""
    joblib = pytest.importorskip("joblib")
    pytest.importorskip("sklearn")
    numpy = pytest.importorskip("numpy")

    from src import embeddings

    path = (
        REPO_ROOT / "models" / "anomaly-detection" / "artifacts"
        / "model_trainer" / "isolation_forest_minilm.joblib"
    )
    if not path.exists() or not embeddings.available():
        pytest.skip("MiniLM model or embedder unavailable")

    model = joblib.load(path)
    vectors = numpy.array(embeddings.embed([
        "Central Bank of Sri Lanka holds the policy rate steady at 8 percent.",
        "Heavy flooding in Ratnapura, Kalu Ganga above major flood level.",
        "Colombo Port container terminal operating normally, no delays.",
        "Nationwide power grid failure across all nine provinces at once.",
    ]))
    scores = -model.decision_function(vectors)

    assert len(set(numpy.round(scores, 6))) > 1, (
        "every event scored identically -- the embedder is producing constant "
        "vectors, which is the zeros bug in a new coat"
    )
