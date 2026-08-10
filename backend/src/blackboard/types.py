"""
src/blackboard/types.py
The board's vocabulary, in one place.

These are the frozen dataclasses the scheduler passes around. They live here
rather than beside the SQLAlchemy models on purpose: a BoardDigest is not a
row, it is a computed view handed to every trigger, and a KnowledgeSource is
never persisted at all. Putting them next to the tables would suggest they are
stored, which is the sort of quiet wrong assumption that costs an afternoon.

They are re-exported from knowledge_sources, which is where they are defined
and where the registry that uses them lives. Two definitions of Activation
would be worse than one import indirection -- this codebase has already been
bitten by the same class existing twice with different shapes.
"""

from __future__ import annotations

from .knowledge_sources import (  # noqa: F401
    Activation,
    BoardDigest,
    KnowledgeSource,
)

__all__ = ["Activation", "BoardDigest", "KnowledgeSource"]
