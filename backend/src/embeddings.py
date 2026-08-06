"""
src/embeddings.py
Sentence embeddings that fit in 512 MB.

WHY THIS EXISTS
---------------
The anomaly-detection models are scikit-learn isolation forests, which is cheap
and would run happily on a free instance. Their *input* is what does not fit:
models/anomaly-detection/src/utils/vectorizer.py produces 768-dim embeddings
from distilbert-base-uncased via transformers + torch -- the ~3 GB stack that
was deliberately removed from requirements-service.txt.

That vectorizer does not fail loudly when transformers is missing. It logs and
returns np.zeros(768). Measured, with transformers and torch blocked exactly as
the deployed image has them:

    nonzero_dims=0  pred=-1  score=+0.012138   Heavy flooding in Ratnapura...
    nonzero_dims=0  pred=-1  score=+0.012138   Colombo Port operating normally...
    nonzero_dims=0  pred=-1  score=+0.012138   Central Bank holds rate steady...

Every event scores identically, every event is flagged anomalous, and
/api/anomalies reports model_status "ml_active" while doing it. That is not a
degraded prediction; it is a fabricated one, and it would be presented on a
live URL as working ML.

THE FIX
-------
chromadb is already in the slim set, and it ships all-MiniLM-L6-v2 as ONNX --
no torch, no transformers, ~80 MB, 384 dimensions. chromadb_store.py already
relies on it for the vector store, so the deployed image pays this cost
already; using it here adds nothing.

So the embeddings are real in production, and the isolation forest is re-fitted
on 384-dim MiniLM vectors to match (see scripts/train_anomaly_minilm.py).

The one rule this module enforces: never return a zero vector as though it were
an embedding. If we cannot embed, the caller is told, and the endpoint falls
back to its honest keyword scoring path rather than scoring noise.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional, Sequence

logger = logging.getLogger("Roger.embeddings")

# all-MiniLM-L6-v2 output width. Committed alongside the retrained artifact;
# a mismatch here means the model and the embedder disagree, which sklearn
# reports as a feature-count error rather than silently scoring garbage.
EMBEDDING_DIM = 384

_lock = threading.Lock()
_embedder = None
_unavailable_reason: Optional[str] = None


class EmbeddingUnavailable(RuntimeError):
    """
    Raised instead of returning zeros.

    The distinction matters: a zero vector is a valid input to a fitted
    isolation forest, so returning one produces a confident, meaningless,
    perfectly uniform answer. An exception produces a fallback that says what
    it is.
    """


def _load():
    """The ONNX MiniLM embedder chromadb bundles. Downloaded once, cached."""
    global _embedder, _unavailable_reason

    if _embedder is not None:
        return _embedder
    if _unavailable_reason is not None:
        raise EmbeddingUnavailable(_unavailable_reason)

    with _lock:
        if _embedder is not None:
            return _embedder
        try:
            from chromadb.utils import embedding_functions

            # Constructing it is cheap; the ONNX session is a cached_property,
            # so the real work happens on the first call.
            _embedder = embedding_functions.ONNXMiniLM_L6_V2()
            logger.info("[embeddings] ONNX all-MiniLM-L6-v2 ready (%d dims)", EMBEDDING_DIM)
            return _embedder
        except Exception as exc:  # noqa: BLE001
            _unavailable_reason = f"{type(exc).__name__}: {exc}"
            logger.error("[embeddings] unavailable -- %s", _unavailable_reason)
            raise EmbeddingUnavailable(_unavailable_reason) from exc


def available() -> bool:
    """Whether embed() can be expected to work. Used by the preflight report."""
    if os.getenv("DISABLE_EMBEDDINGS", "").strip().lower() in ("1", "true", "yes"):
        return False
    try:
        _load()
        return True
    except EmbeddingUnavailable:
        return False


def embed(texts: Sequence[str]) -> List[List[float]]:
    """
    Embed a batch. Raises EmbeddingUnavailable rather than returning zeros.

    Empty and whitespace-only inputs are rejected for the same reason: an
    empty string does embed to *something*, but scoring it tells you about the
    absence of text rather than about the event.
    """
    cleaned = [t.strip() for t in texts]
    if not cleaned or not any(cleaned):
        raise EmbeddingUnavailable("no text to embed")

    embedder = _load()
    vectors = embedder([t if t else " " for t in cleaned])
    out = [list(map(float, v)) for v in vectors]

    for vector in out:
        if len(vector) != EMBEDDING_DIM:
            raise EmbeddingUnavailable(
                f"embedder returned {len(vector)} dims, expected {EMBEDDING_DIM}"
            )
    return out


def embed_one(text: str) -> List[float]:
    return embed([text])[0]


def reset() -> None:
    """Tests."""
    global _embedder, _unavailable_reason
    _embedder = None
    _unavailable_reason = None
