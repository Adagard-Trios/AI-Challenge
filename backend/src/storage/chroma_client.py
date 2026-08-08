"""
src/storage/chroma_client.py
One place that decides how to reach ChromaDB.

WHY
---
Three modules built their own PersistentClient against a local directory:

    src/storage/chromadb_store.py   semantic dedup of events   (Roger_events)
    src/utils/db_manager.py         chunked raw posts for RAG  (Roger_feeds)
    src/rag.py                      the chatbot's retrieval

A directory on local disk cannot be shared. Every replica embeds and stores
into its own copy, so semantic dedup only ever sees what THAT pod collected --
which quietly turns a cross-replica duplicate check into a per-pod one, and the
whole point of the semantic tier is that it catches what the exact-hash tier
misses. On Render's free tier the directory is also ephemeral, so the corpus is
destroyed on every deploy.

chromadb 1.3.5 ships a server (`chroma run`) and an HttpClient, so the fix is a
different constructor and no change to any query.

HONEST ABOUT WHAT THIS IS
-------------------------
A Chroma server is a single node. This replaces N divergent local copies with
one correct shared one -- which is the point -- but it is a SHARED service, not
a scaled one, and it becomes a new single point of failure for the read path.
That is a good trade and it is not a scaling win; filing it as one would be
misleading.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("Roger.storage.chroma")


def server_configured() -> bool:
    return bool((os.getenv("CHROMA_HOST") or "").strip())


def describe() -> str:
    """For startup logs and /api/status, so the mode is never a guess."""
    if server_configured():
        return f"server {os.getenv('CHROMA_HOST')}:{os.getenv('CHROMA_PORT', '8000')}"
    return "local directory (per-process; not shared between replicas)"


def get_client(path: Optional[str] = None) -> Any:
    """
    A ChromaDB client: HttpClient against the shared server when CHROMA_HOST is
    set, PersistentClient against `path` otherwise.

    Raises rather than returning None on a configured-but-unreachable server.
    Every caller already wraps construction in a try/except and degrades to
    "no vector store", and silently degrading to a LOCAL client would be worse
    than failing: each replica would build a private corpus while appearing to
    work, and semantic dedup would quietly stop being cross-replica.
    """
    import chromadb
    from chromadb.config import Settings

    settings = Settings(anonymized_telemetry=False, allow_reset=True)

    if server_configured():
        host = (os.getenv("CHROMA_HOST") or "").strip()
        port = int((os.getenv("CHROMA_PORT") or "8000").strip())
        client = chromadb.HttpClient(host=host, port=port, settings=settings)
        # Fail here rather than on the first query, which would surface deep
        # inside an agent cycle as an unrelated-looking error.
        client.heartbeat()
        logger.info("[ChromaDB] using shared server at %s:%s", host, port)
        return client

    return chromadb.PersistentClient(path=path, settings=settings)
