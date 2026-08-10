"""
src/images/search.py
Find posts by picture rather than by word.

TWO LAYERS, BECAUSE THEY ANSWER DIFFERENT QUESTIONS
---------------------------------------------------
**Perceptual hash** answers "is this the same photograph?" It survives
rescaling, recompression and mild cropping, and it is the layer that catches a
2017 flood photograph being reposted as today's news -- which is a real
misinformation check, not a nice-to-have, and is the strongest thing this
feature contributes to the platform's SDG claim.

**CLIP** answers "is this the same kind of scene?" It matches a flooded street
to another flooded street, and it matches a photograph of a person when the
image itself is similar.

Deliberately NOT face recognition. Identifying a specific person across
platforms processes biometric data of people who never consented -- a special
category under Sri Lanka's PDPA No. 9 of 2022 -- and is a different product
with different obligations. Similarity search covers the legitimate uses
(is this image reused? where else has it appeared?) without building an
identity index.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Roger.images.search")

# Hamming distance between two 64-bit perceptual hashes.
#
# 0 is byte-identical after normalisation; up to ~10 survives rescaling and
# recompression; beyond ~16 the images are merely similar-looking and the
# answer stops being trustworthy. 12 is the usual compromise and errs toward
# missing a match rather than asserting a false one -- which is the right way
# round when the output is "this photo is recycled".
PHASH_MAX_DISTANCE = 12

CLIP_MODEL = "openai/clip-vit-base-patch32"
CLIP_COLLECTION = "Roger_images"

_clip = None
_clip_lock = threading.Lock()
_clip_unavailable = False


def _hamming(a: str, b: str) -> Optional[int]:
    """Distance between two hex phash strings, or None if they are not comparable."""
    if not a or not b or len(a) != len(b):
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def _clip_enabled() -> bool:
    """
    CLIP is opt-in, and off by default.

    It is ~600 MB and downloads on first use, which turns the first image
    search into a multi-minute wait that looks like a hang. The layer it adds
    is "similar scene"; the layer that actually answers the question people
    bring to this feature -- has this photograph been posted before? -- is the
    perceptual hash, which is instant and needs nothing.

    So the useful half works out of the box, and the expensive half is a
    deliberate choice: ENABLE_CLIP_SEARCH=1.
    """
    import os

    return os.getenv("ENABLE_CLIP_SEARCH", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _clip_model():
    """Loaded once, lazily: ~600 MB and a network fetch on first use."""
    global _clip, _clip_unavailable

    if _clip is not None or _clip_unavailable:
        return _clip
    if not _clip_enabled():
        return None

    with _clip_lock:
        if _clip is not None or _clip_unavailable:
            return _clip
        try:
            from transformers import CLIPModel, CLIPProcessor

            model = CLIPModel.from_pretrained(CLIP_MODEL)
            model.eval()
            _clip = (model, CLIPProcessor.from_pretrained(CLIP_MODEL))
            logger.info("[images] CLIP ready (%s)", CLIP_MODEL)
        except Exception as exc:  # noqa: BLE001
            _clip_unavailable = True
            logger.info(
                "[images] CLIP unavailable (%s); image search falls back to "
                "perceptual hashing only", exc,
            )
    return _clip


def clip_available() -> bool:
    return _clip_model() is not None


def embed_image(path_or_image) -> Optional[List[float]]:
    """A CLIP embedding for one image, or None if CLIP is not available."""
    loaded = _clip_model()
    if loaded is None:
        return None

    model, processor = loaded
    try:
        import torch
        from PIL import Image

        image = (
            path_or_image if hasattr(path_or_image, "mode")
            else Image.open(path_or_image)
        )
        image = image.convert("RGB")

        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            features = model.get_image_features(**inputs)
            # Normalised, so a dot product is cosine similarity and the
            # distances are comparable across images.
            features = features / features.norm(p=2, dim=-1, keepdim=True)
        return features[0].tolist()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[images] could not embed: %s", exc)
        return None


def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def search_by_image(
    image_bytes: bytes,
    db,
    *,
    limit: int = 20,
    min_similarity: float = 0.75,
) -> Dict[str, Any]:
    """
    Posts whose images match the uploaded one.

    Reports WHICH layer matched, per result. "The same photograph" and "a
    similar scene" are different claims, and collapsing them into one score
    would let a loose visual resemblance read as proof of reuse.
    """
    import io

    from auth.models import IngestedPost, PostImage

    out: Dict[str, Any] = {
        "matches": [], "total": 0,
        "phash_used": False, "clip_used": False,
    }

    try:
        import imagehash
        from PIL import Image

        query_image = Image.open(io.BytesIO(image_bytes))
        query_image.load()
        query_hash = str(imagehash.phash(query_image))
        out["phash_used"] = True
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"Could not read that image: {exc}"
        return out

    query_vector = embed_image(query_image)
    out["clip_used"] = query_vector is not None

    rows = db.query(PostImage, IngestedPost).join(
        IngestedPost, PostImage.post_id == IngestedPost.id
    ).all()

    scored = []
    for image, post in rows:
        distance = _hamming(query_hash, image.phash or "")

        exact = distance is not None and distance <= PHASH_MAX_DISTANCE
        similarity = None

        if query_vector is not None and image.local_path:
            # Resolve through the store: with object storage, local_path is a
            # KEY and the file may have been written by a different pod. A
            # missing file here would silently mean "no similar image" rather
            # than "this replica cannot read it".
            from .store import fetch as _fetch

            readable = _fetch(image.local_path)
            vector = embed_image(readable) if readable else None
            if vector:
                similarity = _cosine(query_vector, vector)

        if not exact and (similarity is None or similarity < min_similarity):
            continue

        scored.append({
            "post_id": post.id,
            "platform": post.platform,
            "poster": post.poster,
            "text": (post.text or "")[:280],
            "url": post.url,
            "image_url": image.url,
            "ocr_text": image.ocr_text,
            "collected_at": post.collected_at.isoformat() if post.collected_at else None,
            # The distinction that matters: same picture, or merely alike.
            "matched_on": "same_image" if exact else "similar_scene",
            "phash_distance": distance,
            "similarity": round(similarity, 4) if similarity is not None else None,
        })

    # Same-image first, then by visual similarity. A recycled photograph is the
    # answer someone is looking for; a lookalike is context.
    scored.sort(
        key=lambda m: (
            0 if m["matched_on"] == "same_image" else 1,
            m["phash_distance"] if m["phash_distance"] is not None else 99,
            -(m["similarity"] or 0),
        )
    )

    out["matches"] = scored[:limit]
    out["total"] = len(scored)
    return out
