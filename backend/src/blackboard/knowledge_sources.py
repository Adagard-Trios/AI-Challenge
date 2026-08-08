"""
src/blackboard/knowledge_sources.py
What can be run, when it is worth running, and what it costs.

WHY THE UNIT IS NOT "AN AGENT"
------------------------------
If knowledge sources were the five domain agents, the scheduler would have five
identical items on its agenda and the answer would always be "run them all" --
a large complexity tax for nothing. The real unit is one level down. Every
domain node has the same internal shape:

    collect_* x3-5  ->  categorize  ->  llm_summary  ->  format_output

which is roughly 23 collect_* methods and 5 LLM summary calls, EVERY ONE OF
WHICH FIRES UNCONDITIONALLY EVERY CYCLE. The meteorological node scrapes five
hardcoded districts whether or not anything is flooding; the intelligence node
collects competitor mentions with an empty watchlist.

At that granularity opportunistic control pays for itself twice: targeted
scraping, and -- much more importantly -- LLM budget.

THE BUDGET IS THE REAL CONSTRAINT
---------------------------------
Groq's free tier is 8,000 tokens per MINUTE, shared across everything, and this
project already hits it (HTTP 413 while summarising a gazette). Five
unconditional LLM summaries per cycle is the floor today. Making them
demand-driven is the single largest saving available, and it IS opportunistic
control.

So every source declares `est_tokens` BEFORE it runs, and the controller
refuses one whose estimate exceeds the remaining window rather than discovering
the limit by hitting it.

trigger() DOES NO I/O
---------------------
It reads a BoardDigest computed once per tick, not once per source. Twenty-five
sources each querying the database to decide whether to run would cost more
than running them. Enforced by a test.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Roger.blackboard.ks")


@dataclass(frozen=True)
class BoardDigest:
    """
    One snapshot of the board, computed once per tick and handed to every
    trigger. Everything a source needs to decide, and nothing that requires
    another query.
    """
    foci: List[Dict[str, Any]] = field(default_factory=list)
    severity_by_domain: Dict[str, float] = field(default_factory=dict)
    last_run: Dict[str, float] = field(default_factory=dict)   # ks -> seconds ago
    tokens_remaining: int = 0

    def focus_urgency(self, *kinds: str) -> float:
        """Strongest current focus of these kinds, or 0."""
        best = 0.0
        for focus in self.foci:
            if not kinds or focus.get("kind") in kinds:
                best = max(best, float(focus.get("urgency") or 0))
        return best

    def focus_values(self, kind: str) -> List[str]:
        return [f["value"] for f in self.foci
                if f.get("kind") == kind and f.get("value")]

    def age_of(self, ks_name: str) -> float:
        """Seconds since this source last ran. Large when never."""
        return float(self.last_run.get(ks_name, 1e9))


@dataclass(frozen=True)
class Activation:
    """A decision to run something, and the reason for it."""
    ks_name: str
    priority: float
    reason: str
    params: Dict[str, Any] = field(default_factory=dict)
    est_tokens: int = 0


@dataclass(frozen=True)
class KnowledgeSource:
    name: str
    domain: str
    est_tokens: int
    min_interval: timedelta
    max_interval: timedelta
    trigger: Callable[[BoardDigest], Optional[Activation]]
    description: str = ""

    # What actually runs when the controller is active. None means "planned
    # but not yet executable" -- the source appears on the agenda and is
    # recorded, which is still useful in shadow, but the controller will never
    # claim to have run it. A source that silently does nothing while
    # reporting success is the failure this whole project keeps producing.
    run: Optional[Callable[[Dict[str, Any]], Any]] = None

    @property
    def executable(self) -> bool:
        return callable(self.run)


# --- priority ---------------------------------------------------------------
#
# One explicit formula rather than a meta-level reasoner. This codebase already
# treats an unexplained score as a number with authority and no accountability,
# and a weighted sum can be unit-tested and argued with.

W_FOCUS = 0.40
W_SEVERITY = 0.20
W_YIELD = 0.15
W_STARVATION = 0.25
W_COST = 0.15


# Starvation is allowed past 1.0 but not without limit.
#
# The original had no ceiling, on the reasoning that a source three times
# overdue must outrank a permanently hot focus. That reasoning is right and the
# implementation was wrong: a source that has NEVER run reports an age of ~1e9
# seconds, so every priority came out in the tens of thousands and the ordering
# between sources became pure noise. Observed on a first run:
#
#     econ.cse 69444.52   met.district_social 34722.42   pol.gazette 11574.15
#
# Ten times overdue contributes 2.5, still far above the most a focus and a
# maximal severity can produce together (0.60), so the guarantee survives and
# the ranking means something again.
MAX_STARVATION = 10.0


def priority(
    *,
    focus_urgency: float = 0.0,
    domain_severity: float = 0.0,
    recent_yield: float = 0.5,
    starvation: float = 0.0,
    cost: float = 0.0,
) -> float:
    return (
        W_FOCUS * max(0.0, min(1.0, focus_urgency))
        + W_SEVERITY * max(0.0, min(1.0, domain_severity))
        + W_YIELD * (1.0 - max(0.0, min(1.0, recent_yield)))
        + W_STARVATION * max(0.0, min(MAX_STARVATION, starvation))
        - W_COST * max(0.0, min(1.0, cost))
    )


def starvation_of(digest: BoardDigest, source: KnowledgeSource) -> float:
    return digest.age_of(source.name) / max(1.0, source.max_interval.total_seconds())


def is_starving(digest: BoardDigest, source: KnowledgeSource) -> bool:
    """
    The hard guarantee, separate from the soft term above.

    Two mechanisms because one is not enough: the weighted term can be starved
    indefinitely by a permanently hot focus, so anything past twice its
    max_interval is promoted regardless of score. This is what makes the worst
    case "degrades to a slower fixed schedule" rather than "goes silent" --
    and going silent is the failure this project keeps producing.
    """
    return starvation_of(digest, source) >= 2.0


# --- the registry -----------------------------------------------------------


# --- what the collectors actually do ----------------------------------------
#
# Each delegates to code that already exists and is already exercised. The
# point of B5 is WHEN things run, not reimplementing WHAT they do -- rewriting
# the collectors at the same time as changing the scheduling would make a
# regression impossible to attribute.


def _run_rivernet(_params):
    from src.utils.utils import tool_rivernet_status

    status = tool_rivernet_status()
    return {"alerts": len((status or {}).get("alerts", []) or []),
            "rivers": len((status or {}).get("rivers", []) or [])}


def _run_gazette(_params):
    from src.utils.utils import scrape_government_gazette_impl

    # Deliberately small: the gazette scraper downloads PDFs, and its own
    # summariser already limits itself to one uncached edition per run to stay
    # inside the model rate limit.
    rows = scrape_government_gazette_impl(max_items=3)
    return {"gazettes": len(rows or [])}


def _run_local_news(_params):
    from src.utils.utils import scrape_local_news_impl

    rows = scrape_local_news_impl(keywords=None, max_articles=30)
    return {"articles": len(rows or [])}


def _run_cse(_params):
    from src.utils.utils import scrape_cse_stock_impl

    return {"cse": bool(scrape_cse_stock_impl())}


def _run_social(params):
    """
    Social collection through the registry, so it passes the pacing gate, the
    daily budget and the challenge backoff exactly as the agent tools do.
    Bypassing that to "just scrape" is how an account gets banned.
    """
    from src.scrapers import registry

    queries = params.get("topic") or params.get("district") or ["sri lanka"]
    results = {}
    for query in list(queries)[:2]:
        outcome = registry.run("scrape_twitter", str(query), max_items=10)
        results[str(query)] = outcome.get("status")
    return results


def _collector(name, domain, *, max_minutes, focus_kinds=(), tokens=0,
               min_minutes=1, description="", run=None):
    """
    A source that scrapes. est_tokens is 0 -- scraping costs network and time,
    not model budget, and conflating the two would make the token gate refuse
    work it does not pay for.
    """
    def trigger(digest: BoardDigest) -> Optional[Activation]:
        urgency = digest.focus_urgency(*focus_kinds) if focus_kinds else 0.0
        starving = is_starving(digest, REGISTRY[name])
        if not starving and urgency < 0.5:
            # Nothing is asking for this and it is not overdue.
            return None

        score = priority(
            focus_urgency=urgency,
            domain_severity=digest.severity_by_domain.get(domain, 0.0),
            starvation=starvation_of(digest, REGISTRY[name]),
        )
        reason = ("overdue" if starving
                  else f"focus urgency {urgency:.2f}")
        params = {}
        for kind in focus_kinds:
            values = digest.focus_values(kind)
            if values:
                params[kind] = values[:3]
        return Activation(name, score, reason, params, tokens)

    return KnowledgeSource(
        name=name, domain=domain, est_tokens=tokens,
        min_interval=timedelta(minutes=min_minutes),
        max_interval=timedelta(minutes=max_minutes),
        trigger=trigger, description=description, run=run,
    )


def _summariser(name, domain, *, max_minutes, tokens, description=""):
    """
    A source that calls the LLM. These are what the token budget is for: five
    of them fire unconditionally every cycle today, forever, into an 8,000
    tokens/minute ceiling.
    """
    def trigger(digest: BoardDigest) -> Optional[Activation]:
        source = REGISTRY[name]
        severity = digest.severity_by_domain.get(domain, 0.0)
        starving = is_starving(digest, source)

        if not starving and severity < 0.5:
            return None
        if digest.tokens_remaining < tokens:
            # Deferred, not attempted. This is the mechanism that actually
            # prevents today's 413s, which are currently discovered by hitting
            # the limit.
            return None

        return Activation(
            name,
            priority(domain_severity=severity,
                     starvation=starvation_of(digest, source),
                     cost=min(1.0, tokens / 4000.0)),
            "overdue" if starving else f"new {domain} severity {severity:.2f}",
            {},
            tokens,
        )

    return KnowledgeSource(
        name=name, domain=domain, est_tokens=tokens,
        min_interval=timedelta(minutes=5),
        max_interval=timedelta(minutes=max_minutes),
        trigger=trigger, description=description,
    )


REGISTRY: Dict[str, KnowledgeSource] = {}


def _register(source: KnowledgeSource) -> None:
    REGISTRY[source.name] = source


# Collectors. max_interval is the floor that guarantees they still run when
# nothing is asking for them.
_register(_collector(
    "met.rivernet", "meteorological", max_minutes=10, run=_run_rivernet,
    description="River gauges. Cheapest, highest-signal input; always runs."))
_register(_collector(
    "met.district_social", "meteorological", max_minutes=120,
    focus_kinds=("district",), run=_run_social,
    description="Social posts for districts a flood focus names, not five "
                "hardcoded ones."))
_register(_collector(
    "pol.official_gazette", "political", max_minutes=360,
    focus_kinds=("district",), run=_run_gazette,
    description="Gazettes publish daily; emergency orders follow floods."))
_register(_collector(
    "econ.cse", "economical", max_minutes=60, run=_run_cse,
    description="Colombo Stock Exchange."))
_register(_collector(
    "econ.local_news", "economical", max_minutes=45, run=_run_local_news,
    description="Five Sri Lankan outlets, round-robin."))
_register(_collector(
    "social.trends", "social", max_minutes=30, focus_kinds=("topic",),
    run=_run_social,
    description="Follows spiking topics rather than a fixed keyword list."))
_register(_collector(
    "intel.competitor_mentions", "intelligence", max_minutes=120,
    focus_kinds=("entity",),
    description="Gated on a non-empty watchlist; today it runs regardless. "
                "No run() yet -- it stays on the agenda and is recorded, but "
                "the controller will never claim to have run it."))

# Summarisers. These are the spend.
for _domain in ("social", "political", "economical", "meteorological",
                "intelligence"):
    _register(_summariser(
        f"{_domain[:4]}.summarise", _domain, max_minutes=30, tokens=1200,
        description=f"LLM summary for {_domain}. Fires unconditionally today."))


def build_agenda(digest: BoardDigest) -> List[Activation]:
    """
    Everything worth running now, most important first.

    A source whose trigger raises is SKIPPED, not fatal: one broken trigger
    must not silence the whole agenda.
    """
    agenda: List[Activation] = []
    for source in REGISTRY.values():
        try:
            activation = source.trigger(digest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ks] %s trigger failed: %s", source.name, exc)
            continue
        if activation is not None:
            agenda.append(activation)

    # Starving sources first regardless of score -- the hard guarantee.
    agenda.sort(
        key=lambda a: (is_starving(digest, REGISTRY[a.ks_name]), a.priority),
        reverse=True,
    )
    return agenda
