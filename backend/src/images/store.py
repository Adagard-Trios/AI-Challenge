"""
src/images/store.py
Where downloaded post images live.

WHY THIS EXISTS
---------------
The pipeline writes to a local directory and records the absolute path on the
PostImage row. That is correct for one process and wrong for a cluster in two
ways, both silent:

  - A path written by the worker means nothing on an API replica. Image search
    reads local_path to embed a candidate, so it would find the row, fail to
    open the file, and return no match -- which looks like "that picture is not
    in the corpus" rather than "that pod cannot see the file".
  - Render's free tier has no persistent disk, so the directory is destroyed on
    every deploy. The rows survive and point at nothing.

Object storage fixes both, and the pipeline already names files by perceptual
hash, so the layout is content-addressed and needs no change: {phash}.{ext} is
already a key.

DELIBERATELY NOT A REAL ReadWriteMany VOLUME
--------------------------------------------
On a single-node cluster a hostPath is effectively RWX and would work. It is
also silently wrong the moment there is a second node, and "works until you
scale" is the failure this whole track exists to remove. MinIO speaks S3, so
the same code path runs against real S3 later without changes.

Unset S3_* keeps the local directory, which is what a laptop runs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Roger.images.store")


def _config() -> Optional[dict]:
    endpoint = (os.getenv("S3_ENDPOINT") or "").strip()
    bucket = (os.getenv("S3_BUCKET") or "").strip()
    if not endpoint or not bucket:
        return None
    return {
        "endpoint": endpoint,
        "bucket": bucket,
        "access_key": (os.getenv("S3_ACCESS_KEY") or "").strip(),
        "secret_key": (os.getenv("S3_SECRET_KEY") or "").strip(),
        "secure": (os.getenv("S3_SECURE", "0").strip().lower()
                   in ("1", "true", "yes", "on")),
    }


def configured() -> bool:
    return _config() is not None


def _client():
    config = _config()
    if config is None:
        return None, None
    try:
        from minio import Minio

        client = Minio(
            config["endpoint"],
            access_key=config["access_key"] or None,
            secret_key=config["secret_key"] or None,
            secure=config["secure"],
        )
        if not client.bucket_exists(config["bucket"]):
            client.make_bucket(config["bucket"])
        return client, config["bucket"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[images] object storage unavailable (%s); using the "
                       "local directory", exc)
        return None, None


def put(local_path: str, key: str) -> Optional[str]:
    """
    Upload and return the stored key, or None when there is no object store.

    None means "the caller's local path is still the truth", which is exactly
    the single-process behaviour -- so this never has to be handled as an
    error.
    """
    client, bucket = _client()
    if client is None:
        return None
    try:
        client.fput_object(bucket, key, local_path)
        return key
    except Exception as exc:  # noqa: BLE001
        logger.warning("[images] could not upload %s: %s", key, exc)
        return None


def fetch(key_or_path: str) -> Optional[str]:
    """
    A path this process can open, downloading from object storage if needed.

    Callers embed and hash real files, so handing back a temp path keeps every
    downstream reader unchanged. A local path that already exists is returned
    untouched -- the single-process case must not pay for a round trip.
    """
    if not key_or_path:
        return None

    if os.path.isabs(key_or_path) and Path(key_or_path).exists():
        return key_or_path

    client, bucket = _client()
    if client is None:
        return key_or_path if Path(key_or_path).exists() else None

    import tempfile

    try:
        suffix = Path(key_or_path).suffix or ".bin"
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.close()
        client.fget_object(bucket, key_or_path, handle.name)
        return handle.name
    except Exception as exc:  # noqa: BLE001
        logger.debug("[images] could not fetch %s: %s", key_or_path, exc)
        return None
