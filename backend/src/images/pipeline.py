"""
src/images/pipeline.py
Fetch a post's images, hash them, read the text in them.

Everything here is best-effort by construction. An image that cannot be
downloaded, hashed or read must cost that image and nothing more -- never the
post it belongs to, and never the collection run. The posts are what the user
pressed the button for.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("Roger.images")

IMAGE_DIR = Path(
    os.getenv("IMAGE_STORE_DIR")
    or (Path(__file__).resolve().parent.parent.parent / "data" / "images")
)

# A social image is single-digit MB. Anything larger is a mistake or a way to
# fill the disk, and it is not worth an OCR pass either.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
DOWNLOAD_TIMEOUT = 20

# Below this an OCR read is noise rather than text. Kept low rather than
# strict: a half-read flood warning is still a signal worth having, and the
# score travels with it so the UI can mark it.
MIN_OCR_CONFIDENCE = 0.35

_ocr = None
_ocr_lock = threading.Lock()
_ocr_unavailable = False


@dataclass
class ImageResult:
    url: str
    local_path: Optional[str] = None
    phash: Optional[str] = None
    ocr_text: str = ""
    ocr_lang: Optional[str] = None
    ocr_confidence: Optional[float] = None
    error: Optional[str] = None

    @property
    def has_text(self) -> bool:
        return bool(self.ocr_text.strip())


def ocr_available() -> bool:
    """Whether text extraction can run at all, for the preflight and the UI."""
    return _reader() is not None


def _reader():
    """
    The RapidOCR reader, built once.

    Model files are downloaded on first use, so this is deliberately lazy --
    importing this module must not reach out to the network.
    """
    global _ocr, _ocr_unavailable

    if _ocr is not None or _ocr_unavailable:
        return _ocr

    with _ocr_lock:
        if _ocr is not None or _ocr_unavailable:
            return _ocr
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ocr = RapidOCR()
            logger.info("[images] OCR ready (RapidOCR / PP-OCR on onnxruntime)")
        except Exception as exc:  # noqa: BLE001
            _ocr_unavailable = True
            logger.warning(
                "[images] OCR unavailable (%s). Images will still be stored and "
                "searchable; their text will not be extracted.", exc,
            )
    return _ocr


def _detect_script(text: str) -> str:
    """
    Which script the extracted text is in.

    Reuses the Unicode-range approach from the anomaly model's language
    detector rather than a probabilistic classifier: Sinhala and Tamil occupy
    distinct blocks, so this is exact, and exactness matters when it decides
    whether to trust a read.
    """
    sinhala = sum(1 for c in text if 0x0D80 <= ord(c) <= 0x0DFF)
    tamil = sum(1 for c in text if 0x0B80 <= ord(c) <= 0x0BFF)
    latin = sum(1 for c in text if c.isalpha() and ord(c) < 128)

    total = sinhala + tamil + latin
    if not total:
        return "unknown"
    if sinhala / total > 0.3:
        return "sinhala"
    if tamil / total > 0.3:
        return "tamil"
    return "english"


def _download(url: str, session=None) -> Optional[bytes]:
    try:
        import requests

        response = (session or requests).get(
            url,
            timeout=DOWNLOAD_TIMEOUT,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; RogerIntel/1.0)"},
        )
        if response.status_code != 200:
            return None

        # Read with a ceiling rather than trusting Content-Length, which a
        # server is free to lie about.
        chunks, total = [], 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                logger.debug("[images] %s exceeds %d bytes; skipped", url, MAX_IMAGE_BYTES)
                return None
            chunks.append(chunk)
        return b"".join(chunks)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[images] could not fetch %s: %s", url, exc)
        return None


def _read_text(path: Path) -> tuple:
    """(text, confidence) for one image, or ("", None)."""
    reader = _reader()
    if reader is None:
        return "", None

    try:
        result, _ = reader(str(path))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[images] OCR failed on %s: %s", path.name, exc)
        return "", None

    if not result:
        return "", None

    # RapidOCR returns [box, text, score] per detected line. Averaging the
    # scores gives a usable per-image confidence; keeping every line preserves
    # reading order, which matters for a notice or a sign.
    lines, scores = [], []
    for row in result:
        try:
            text, score = row[1], float(row[2])
        except (IndexError, TypeError, ValueError):
            continue
        if text and text.strip():
            lines.append(text.strip())
            scores.append(score)

    if not lines:
        return "", None

    return "\n".join(lines), sum(scores) / len(scores)


def process_image(url: str, session=None) -> ImageResult:
    """
    Fetch one image, hash it, read it. Never raises.

    Deduplicated by perceptual hash rather than URL: the same photograph is
    served from different CDN URLs constantly, and OCR is the expensive step.
    """
    result = ImageResult(url=url)

    data = _download(url, session=session)
    if not data:
        result.error = "download failed"
        return result

    try:
        import imagehash
        from PIL import Image

        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        import io

        image = Image.open(io.BytesIO(data))
        image.load()
        result.phash = str(imagehash.phash(image))

        # Named by content hash, so the same picture from two URLs is stored
        # once and the filename is stable across runs.
        digest = hashlib.sha256(data).hexdigest()[:24]
        key = f"{digest}.{(image.format or 'png').lower()}"
        path = IMAGE_DIR / key
        if not path.exists():
            path.write_bytes(data)
        result.local_path = str(path)

        # Also to object storage when configured, and record the KEY rather
        # than the path.
        #
        # An absolute path written by the worker means nothing on an API
        # replica: image search opens local_path to embed a candidate, so it
        # would find the row, fail to open the file, and report no match --
        # which reads as "that picture is not in the corpus" rather than "this
        # pod cannot see the file". The name is already a content hash, so the
        # key needs no new scheme.
        from .store import put as _put

        stored = _put(str(path), key)
        if stored:
            result.local_path = stored

    except Exception as exc:  # noqa: BLE001
        result.error = f"decode failed: {exc}"
        return result

    # OCR reads the file just written, not the stored key -- it is still on
    # this disk and a round trip to object storage would be pure cost.
    text, confidence = _read_text(path)
    if text and (confidence is None or confidence >= MIN_OCR_CONFIDENCE):
        result.ocr_text = text
        result.ocr_confidence = confidence
        result.ocr_lang = _detect_script(text)
    elif text:
        # Read something, but not well enough to treat as text. Recorded with
        # its score rather than discarded, so the UI can show it as uncertain.
        result.ocr_text = text
        result.ocr_confidence = confidence
        result.ocr_lang = _detect_script(text)
        logger.debug("[images] low-confidence read (%.2f) on %s", confidence, url)

    return result


def ingest_post_images(post_id: str, urls: List[str], db) -> List[ImageResult]:
    """
    Process a post's images and persist them.

    Returns the results so the caller can append the extracted text to the post
    before classification -- which is the whole point of doing this before the
    LLM sees it, rather than after.
    """
    from auth.models import PostImage

    results: List[ImageResult] = []
    if not urls:
        return results

    try:
        import requests

        session = requests.Session()
    except Exception:  # noqa: BLE001
        session = None

    for url in urls:
        result = process_image(url, session=session)
        results.append(result)

        if result.error and not result.phash:
            continue

        try:
            db.add(PostImage(
                post_id=post_id,
                url=url,
                local_path=result.local_path,
                phash=result.phash,
                ocr_text=result.ocr_text or None,
                ocr_lang=result.ocr_lang,
                ocr_confidence=result.ocr_confidence,
            ))
        except Exception:  # noqa: BLE001
            logger.exception("[images] could not record %s", url)

    return results


def text_from(results: List[ImageResult]) -> str:
    """
    Extracted text, formatted for appending to a post.

    Labelled rather than concatenated silently: a reader of the resulting event
    should be able to tell which words came from a caption a human typed and
    which came from a machine reading a photograph, because the two deserve
    different levels of trust.
    """
    parts = [r.ocr_text.strip() for r in results if r.has_text]
    if not parts:
        return ""
    return "\n\n[text in image] " + "\n[text in image] ".join(parts)
