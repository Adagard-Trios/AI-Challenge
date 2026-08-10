"""
src/blackboard/
A shared, decaying picture of what is currently happening.

WHAT THIS IS FOR
----------------
The five domain agents cannot see each other, the parent state, or the previous
cycle. Each is invoked with an EMPTY DICT (combinedAgentGraph.py:65 and its four
siblings), the parent state argument is accepted and never read, there is no
checkpointer, and a fresh CombinedAgentState is built every cycle. The only
place any cross-domain evidence meets is the aggregator, which consults the
storage layer after the fact.

So a flood alert cannot make the meteorological agent look at Ratnapura, and a
tariff notice cannot make the economic agent look at that sector. Every arrow in
that chain already exists as code -- rivernet status, district social collection,
canonicalise_many, StoryTracker, exposure scoring -- and none of them are
connected, because nothing shares a board.

THE HONEST SCOPE
----------------
Knowledge sources are NOT the five agents. At that granularity the scheduler has
five identical items on its agenda and the answer is always "run them all",
which is a large complexity tax for nothing. The real unit is one level down:
roughly 23 collect_* methods and 5 LLM summary calls, every one of which fires
unconditionally every cycle whether or not anything changed.

Deliberately NOT built here, and each omission is a decision rather than an
oversight: a meta-level control blackboard that reasons about scheduling (one
explainable weighted formula instead); a hypothesis lattice with confidence
propagation (there are no competing interpretations to arbitrate); raw posts as
a board layer (highest volume, lowest value -- they stay in ChromaDB and are
referenced by id).

STAGING
-------
B0 is this package: models, types, a store and the decay maths. Nothing imports
it on any live path, so it changes no behaviour. It is written first so the
stages that follow are additive rather than a rewrite.
"""
