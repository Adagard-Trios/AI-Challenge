"""
backend/scripts/train_anomaly_minilm.py
Re-fit the anomaly isolation forest on embeddings that exist in production.

The committed isolation forests take 768-dim distilBERT vectors, which the
deployed image cannot produce -- transformers and torch are not installed, and
the vectorizer silently returns np.zeros(768) instead of failing. Scoring that
gives every event the same answer while reporting "ml_active".

This re-fits the same algorithm on 384-dim all-MiniLM-L6-v2 ONNX embeddings,
which chromadb already ships and the slim image already carries. Same model
family, same unsupervised premise, an input the production container can
actually compute.

Training corpus: the real collected Sri Lankan events in backend/data --
the district/political feed dataset plus the daily feed exports. Isolation
forests are unsupervised, so no labels are needed; contamination sets the
expected anomaly rate.

    python scripts/train_anomaly_minilm.py

Writes models/anomaly-detection/artifacts/model_trainer/isolation_forest_minilm.joblib
plus a sidecar .json recording what it was fitted on, so staleness is visible
rather than assumed.
"""

from __future__ import annotations

import csv
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Some exported rows carry a whole article body in one cell.
csv.field_size_limit(10**8)

ARTIFACT_DIR = REPO / "models" / "anomaly-detection" / "artifacts" / "model_trainer"
MODEL_PATH = ARTIFACT_DIR / "isolation_forest_minilm.joblib"
META_PATH = ARTIFACT_DIR / "isolation_forest_minilm.json"

# Share of the corpus the model should treat as anomalous. 0.08 keeps the alert
# volume usable: on a feed of ~150 events a day, a higher rate produces more
# flags than anyone reads, which is how alerting gets ignored.
CONTAMINATION = 0.08

MIN_CORPUS = 100        # below this the forest just memorises

# TRAIN ON WHAT YOU SCORE.
#
# /api/anomalies scores `summary` -- an LLM-written event summary, median 159
# chars. The vector store also holds Roger_feeds: 3,503 chunks of raw source
# documents, median 968 chars, including OCR'd Sinhala gazette PDFs. Those are
# 93% of the available text and a completely different distribution.
#
# Training on them was measurably wrong: the resulting model flagged 6 of 7
# ordinary hand-written Sri Lankan news sentences as anomalous, because next to
# a gazette chunk an ordinary sentence *is* unusual. It would have looked like a
# working detector while scoring the wrong thing.
#
# This band keeps summary-shaped text and drops raw chunks.
MIN_CHARS = 40
MAX_CHARS = 600


def _text_columns(row: dict) -> str:
    """
    The scored field, matching what /api/anomalies scores at runtime.

    Runtime reads `summary`. The dataset exports use `text`/`title`, so those
    are folded in here -- training on a different field than we score on is a
    quiet way to build a model that never works.
    """
    for key in ("summary", "text", "title", "content"):
        value = (row.get(key) or "").strip()
        if MIN_CHARS <= len(value) <= MAX_CHARS:
            return value
    return ""


def _from_chromadb() -> list[str]:
    """
    The vector store, which is where most of the collected corpus actually is.

    The CSV exports look larger than they are: political_feeds_202608.csv has
    665 rows but only 12 distinct documents -- the same handful of posts
    re-exported on every cycle. ChromaDB holds the deduplicated set.
    """
    path = BACKEND / "data" / "chromadb"
    if not path.exists():
        return []

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(path))
        out: list[str] = []
        for collection in client.list_collections():
            handle = client.get_collection(collection.name)
            count = handle.count()
            if not count:
                continue
            got = handle.get(include=["documents"])
            docs = [
                d.strip() for d in (got.get("documents") or [])
                if d and MIN_CHARS <= len(d.strip()) <= MAX_CHARS
            ]
            out.extend(docs)
            print(f"    chromadb:{collection.name}: {len(docs)} kept of {count}")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"  ! chromadb unavailable: {exc}")
        return []


def load_corpus() -> list[str]:
    texts: list[str] = list(_from_chromadb())
    sources: list[str] = []

    patterns = [
        BACKEND / "data" / "datasets" / "*" / "*.csv",
        BACKEND / "data" / "feeds" / "*.csv",
    ]
    for pattern in patterns:
        for path in sorted(glob.glob(str(pattern))):
            try:
                with open(path, encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
            except Exception as exc:  # noqa: BLE001
                print(f"  ! skipped {path}: {exc}")
                continue

            found = [t for t in (_text_columns(r) for r in rows) if t]
            if found:
                texts.extend(found)
                sources.append(f"{Path(path).name}:{len(found)}")

    # Deduplicate: the daily exports overlap heavily, and duplicates teach the
    # forest that a repeated event is normal by weight of repetition alone.
    seen = set()
    unique = []
    for text in texts:
        key = text[:200].lower()
        if key not in seen:
            seen.add(key)
            unique.append(text)

    print(f"  corpus: {len(unique)} unique documents from {len(sources)} files")
    for source in sources:
        print(f"    {source}")
    return unique


def main() -> int:
    try:
        from sklearn.ensemble import IsolationForest
    except ImportError:
        print("scikit-learn is required to train. pip install scikit-learn")
        return 1

    import joblib
    import numpy as np

    from src import embeddings

    print("Loading corpus...")
    corpus = load_corpus()
    if len(corpus) < MIN_CORPUS:
        print(f"Refusing to train on {len(corpus)} documents (need >= {MIN_CORPUS}).")
        return 1

    print(f"Embedding {len(corpus)} documents with ONNX all-MiniLM-L6-v2...")
    vectors = np.array(embeddings.embed(corpus), dtype=np.float32)
    print(f"  matrix: {vectors.shape}")

    if vectors.shape[1] != embeddings.EMBEDDING_DIM:
        print(f"Unexpected width {vectors.shape[1]}")
        return 1

    print(f"Fitting IsolationForest (contamination={CONTAMINATION})...")
    model = IsolationForest(
        n_estimators=200,
        contamination=CONTAMINATION,
        max_samples="auto",
        random_state=42,
        n_jobs=1,          # a free instance has one usable core
    )
    model.fit(vectors)

    scores = model.decision_function(vectors)
    flagged = int((model.predict(vectors) == -1).sum())
    print(f"  flagged {flagged}/{len(corpus)} ({flagged / len(corpus):.1%}) on the training set")
    print(f"  score range: {scores.min():+.4f} .. {scores.max():+.4f}")

    # A single distinct score means the embedder produced constant vectors --
    # the exact failure this retrain exists to remove. Never ship that.
    if len(set(np.round(scores, 6))) < 2:
        print("ABORT: all scores identical; embeddings are not varying.")
        return 1

    # --- does it generalise? ------------------------------------------------
    #
    # Training-set flag rate always lands near `contamination` -- that is what
    # the parameter does, and reporting it as evidence would be circular. The
    # question is what the model does with text it has not seen.
    #
    # This matters more than usual here. The first fit of this script trained on
    # 3,449 documents that were mostly raw gazette chunks and flagged 6 of 7
    # ordinary news sentences. It looked healthy by every training-set measure.
    print("\nValidating on held-out data...")
    rng = np.random.default_rng(42)
    index = rng.permutation(len(vectors))
    cut = int(len(vectors) * 0.8)
    train_idx, held_idx = index[:cut], index[cut:]

    from sklearn.ensemble import IsolationForest as _IF
    probe = _IF(
        n_estimators=200, contamination=CONTAMINATION,
        max_samples="auto", random_state=42, n_jobs=1,
    ).fit(vectors[train_idx])

    held_flagged = int((probe.predict(vectors[held_idx]) == -1).sum())
    held_rate = held_flagged / max(1, len(held_idx))
    print(f"  held-out flag rate: {held_rate:.1%} ({held_flagged}/{len(held_idx)}), "
          f"expected around {CONTAMINATION:.0%}")

    # Three times the configured rate means the model is not describing the
    # distribution, it is memorising the training set. A detector that flags
    # everything is indistinguishable from no detector, but it reports
    # "ml_active" while doing it -- which is worse, because it is believed.
    if held_rate > CONTAMINATION * 3:
        print(
            f"\nABORT: the model flags {held_rate:.0%} of unseen documents.\n"
            f"  That is not a detector -- it is an overfit on a corpus that is\n"
            f"  too small ({len(corpus)} documents) or too narrow to describe\n"
            f"  what 'normal' looks like.\n\n"
            f"  Nothing was written. Collect more events and run this again;\n"
            f"  /api/anomalies keeps using its labelled heuristic scoring until\n"
            f"  a model earns its place."
        )
        return 1

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)

    META_PATH.write_text(json.dumps({
        "model": "IsolationForest",
        "embedder": "chromadb ONNXMiniLM_L6_V2 (all-MiniLM-L6-v2)",
        "dimensions": embeddings.EMBEDDING_DIM,
        "contamination": CONTAMINATION,
        "n_estimators": 200,
        "training_documents": len(corpus),
        "flagged_in_training": flagged,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Fitted on ONNX MiniLM embeddings so inference runs on a 512 MB "
            "instance. The 768-dim distilBERT forests need transformers+torch, "
            "which the deployed image does not install."
        ),
    }, indent=2), encoding="utf-8")

    print(f"\nWrote {MODEL_PATH.relative_to(REPO)}")
    print(f"Wrote {META_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
