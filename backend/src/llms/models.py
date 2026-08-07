"""
src/llms/models.py
Which Groq models this project uses, in one place.

WHY THIS EXISTS
---------------
The model IDs were hardcoded at two call sites, and one of them stopped
existing. src/rag.py asked for meta-llama/llama-4-maverick-17b-128e-instruct,
which Groq deprecated on 20 February 2026; every chatbot message had been
failing with:

    404 - The model `meta-llama/llama-4-maverick-17b-128e-instruct` does not exist

Nothing surfaced that. The RAG layer caught the exception, logged it, and
returned an error string, so the only symptom was a chatbot that never answered
-- indistinguishable from it being slow, or from the key being wrong.

Groq deprecated six models during 2026 alone. This will happen again, so the
IDs live here, come from the environment, and are checked against
`client.models.list()` at startup (see src/preflight.py) rather than being
discovered by a user mid-conversation.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger("Roger.llms")

# Agent classification, entity extraction, story briefs. Still current.
DEFAULT_AGENT_MODEL = "openai/gpt-oss-20b"

# The Roger chatbot. Groq's own stated migration target for Maverick, and the
# larger model is the right trade for a conversational surface: it runs once per
# question rather than once per event, so the extra latency is affordable where
# it would not be in the agent loop.
DEFAULT_CHAT_MODEL = "openai/gpt-oss-120b"


def agent_model() -> str:
    return (os.getenv("GROQ_MODEL") or "").strip() or DEFAULT_AGENT_MODEL


def chat_model() -> str:
    return (os.getenv("GROQ_CHAT_MODEL") or "").strip() or DEFAULT_CHAT_MODEL


def configured_models() -> List[str]:
    """Everything this process will ask Groq for. Used by the preflight."""
    return sorted({agent_model(), chat_model()})


def available_models(api_key: Optional[str] = None) -> Optional[List[str]]:
    """
    What the key can actually reach, or None if the question cannot be answered.

    None means "could not check" -- no key, no network, SDK missing -- and is
    deliberately distinct from an empty list, which would mean "checked, and
    there is nothing". A checker that cannot tell those apart reports a
    configuration error every time the network hiccups, and gets ignored.
    """
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        return None

    try:
        from groq import Groq

        return sorted(m.id for m in Groq(api_key=key).models.list().data)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[llms] could not list Groq models: %s", exc)
        return None
