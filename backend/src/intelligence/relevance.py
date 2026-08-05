"""
src/intelligence/relevance.py
How much does this event matter to THIS business?

The platform served an identical feed to every user. Everstream's value is not
that it monitors global risk -- plenty do -- it is that it surfaces the threats
relevant to a particular organisation's own suppliers and trade lanes. That
requires two things this system did not model: what an event is about
(src/intelligence/taxonomy.py) and what the reader depends on (ExposureProfile).
This joins them.

Deliberately a pure function. No database, no network, no LLM. Relevance is the
thing a user will argue with -- "why is this ranked above that?" -- so it has to
be explainable and reproducible, and every input has to be visible in the
signature. That also makes it exhaustively testable, which a scoring rule that
drives what people see should be.

`matched_on` is not decoration. A score with no explanation is the
`compliance_volatility: 0.7` problem again: a number with authority and no
accountability. Every score returns the reasons that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from .taxonomy import normalise

# What a match is worth, highest first.
#
# The ordering encodes how directly a hit bears on the business:
#   supplier        a named counterparty. Nothing is more specific.
#   infrastructure  the port or airport goods physically move through.
#   district        where the business actually is.
#   lane            a named route, weaker than the port itself.
#   sector          industry-wide; real, but shared with every competitor.
#   keyword         user's own free text, unmodelled and unvalidated.
WEIGHTS: Dict[str, float] = {
    "supplier": 1.00,
    "infrastructure": 0.85,
    "district": 0.80,
    "lane": 0.60,
    "sector": 0.45,
    "keyword": 0.35,
}

# An event where your district is AFFECTED (it flooded) matters more than one
# where it is merely the ACTOR (its council passed a bylaw) or a passing
# mention. Applied multiplicatively so it shades the score without inverting
# the weight ordering above.
ROLE_MULTIPLIER: Dict[str, float] = {
    "affected": 1.00,
    "actor": 0.75,
    "mentioned": 0.60,
}

# Entities outside the seed vocabulary are the extractor's guess, usually a
# company name. Still useful -- that is how supplier matching works at all --
# but discounted, because a hallucinated org name should not outrank a district.
UNKNOWN_ENTITY_DISCOUNT = 0.85

# Which exposure field each entity type is checked against.
_TYPE_TO_FIELDS: Dict[str, Tuple[str, ...]] = {
    "ORG": ("suppliers",),
    "INFRASTRUCTURE": ("infrastructure",),
    "PLACE": ("districts",),
    "LANE": ("lanes",),
    "SECTOR": ("sectors",),
}

# Exposure field -> the weight key it scores under.
_FIELD_TO_WEIGHT: Dict[str, str] = {
    "suppliers": "supplier",
    "infrastructure": "infrastructure",
    "districts": "district",
    "lanes": "lane",
    "sectors": "sector",
}

# How each field reads in the UI badge: "your Gampaha facility".
_FIELD_PHRASING: Dict[str, str] = {
    "suppliers": "your supplier {name}",
    "infrastructure": "{name}, which you depend on",
    "districts": "your {name} operations",
    "lanes": "your {name} route",
    "sectors": "the {name} sector",
    "keywords": 'your keyword "{name}"',
}


@dataclass(frozen=True)
class Exposure:
    """
    What a business depends on, normalised once.

    Built from an ExposureProfile row (or a plain dict) so the scorer never
    touches the ORM and can be tested with literals.
    """

    districts: Tuple[str, ...] = ()
    infrastructure: Tuple[str, ...] = ()
    lanes: Tuple[str, ...] = ()
    sectors: Tuple[str, ...] = ()
    suppliers: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()

    # {field: {normalised: original}} — normalised for matching, original for
    # display, because "your GAMPAHA operations" reads badly in a badge.
    _index: Dict[str, Dict[str, str]] = field(
        default_factory=dict, compare=False, repr=False
    )

    @classmethod
    def from_profile(cls, profile) -> "Exposure":
        """Accepts an ExposureProfile row, its as_dict(), or a plain dict."""
        if profile is None:
            return cls.empty()

        get = (
            profile.get
            if isinstance(profile, dict)
            else lambda key, default=None: getattr(profile, key, default)
        )

        def clean(key):
            # `v is not None` before str(): str(None) is "None", which is
            # truthy, so a null in the stored JSON array would become a
            # phantom exposure entry literally named "None" -- matchable by
            # any entity the extractor happened to call that.
            return tuple(
                str(v).strip()
                for v in (get(key) or [])
                if v is not None and str(v).strip()
            )

        exposure = cls(
            districts=clean("districts"),
            infrastructure=clean("infrastructure"),
            lanes=clean("lanes"),
            sectors=clean("sectors"),
            suppliers=clean("suppliers"),
            keywords=clean("keywords"),
        )
        exposure._build_index()
        return exposure

    @classmethod
    def empty(cls) -> "Exposure":
        exposure = cls()
        exposure._build_index()
        return exposure

    def _build_index(self) -> None:
        for name in ("districts", "infrastructure", "lanes", "sectors",
                     "suppliers", "keywords"):
            table = {}
            for value in getattr(self, name):
                key = normalise(value)
                if key:
                    table[key] = value
            self._index[name] = table

    def is_empty(self) -> bool:
        """
        A user who has declared nothing must get the unranked feed.

        Scoring against an empty profile would mark every event irrelevant and
        quietly empty the feed for anyone who has not filled the form in -- the
        caller has to check this, which is why it is on the type.
        """
        return not any(self._index.values())

    def lookup(self, field_name: str, value: str) -> Optional[str]:
        """Original spelling of a match, or None."""
        return self._index.get(field_name, {}).get(normalise(value))


@dataclass(frozen=True)
class Relevance:
    """A score and the reasons for it. Never one without the other."""

    score: float
    matched_on: Tuple[str, ...]
    # Machine-readable version of the same thing, for filtering and analytics.
    matches: Tuple[Dict[str, str], ...] = ()

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "matched_on": list(self.matched_on),
            "matches": [dict(m) for m in self.matches],
        }


def score_event(
    entities: Iterable[dict],
    exposure: Exposure,
    *,
    summary: str = "",
) -> Optional[Relevance]:
    """
    Score one event against one business's exposure.

    Returns None when there is nothing to score against -- an empty profile.
    That is distinct from Relevance(0.0, ()), which means "we looked and this
    does not touch you". The caller must keep them apart: the first leaves the
    feed unranked, the second ranks the event last.

    The score is the strongest single match, not a sum. Three weak sector hits
    should not outrank one named supplier, and summing lets a noisy extractor
    inflate anything. Additional matches widen `matched_on` and add a small
    corroboration bonus, capped well below the next weight up.
    """
    if exposure is None or exposure.is_empty():
        return None

    matches: List[Dict[str, str]] = []

    for entity in entities or []:
        if not isinstance(entity, dict):
            continue

        etype = str(entity.get("type", "")).upper()
        name = str(entity.get("name", "")).strip()
        if not name:
            continue

        role = str(entity.get("role", "mentioned")).lower()
        role_factor = ROLE_MULTIPLIER.get(role, ROLE_MULTIPLIER["mentioned"])
        known_factor = 1.0 if entity.get("known") else UNKNOWN_ENTITY_DISCOUNT

        for field_name in _TYPE_TO_FIELDS.get(etype, ()):
            original = exposure.lookup(field_name, name)
            if original is None:
                continue

            weight = WEIGHTS[_FIELD_TO_WEIGHT[field_name]]
            matches.append({
                "field": field_name,
                "name": original,
                "entity_type": etype,
                "role": role,
                "weight": round(weight * role_factor * known_factor, 4),
                "reason": _FIELD_PHRASING[field_name].format(name=original),
            })

    # Keywords are matched against the summary text, not entities: they exist
    # precisely for the things the taxonomy does not model.
    if summary and exposure._index.get("keywords"):
        lowered = f" {normalise(summary)} "
        for key, original in exposure._index["keywords"].items():
            if key and f" {key} " in lowered:
                matches.append({
                    "field": "keywords",
                    "name": original,
                    "entity_type": "KEYWORD",
                    "role": "mentioned",
                    "weight": WEIGHTS["keyword"],
                    "reason": _FIELD_PHRASING["keywords"].format(name=original),
                })

    if not matches:
        return Relevance(score=0.0, matched_on=(), matches=())

    matches.sort(key=lambda m: m["weight"], reverse=True)
    best = matches[0]["weight"]

    # Corroboration across distinct exposure fields. Capped at 0.1 so it can
    # never lift a sector-only match past an infrastructure one -- the ordering
    # in WEIGHTS is the product decision and arithmetic must not overturn it.
    distinct_fields = len({m["field"] for m in matches})
    bonus = min(0.10, 0.05 * (distinct_fields - 1))

    return Relevance(
        score=round(min(1.0, best + bonus), 4),
        matched_on=tuple(m["reason"] for m in matches),
        matches=tuple(matches),
    )


# Above this an event is worth surfacing as "relevant to me".
#
# Set at the keyword weight, deliberately. A keyword is something the user
# typed because they care about it; a threshold above 0.35 would mean an
# explicit keyword match never qualified as relevant, which is backwards.
#
# What this admits and excludes:
#   0.85  your port, affected          in
#   0.80  your district, affected      in
#   0.45  your sector, affected        in
#   0.36  your lane, mentioned         in
#   0.35  your own keyword             in
#   0.27  your sector, passing mention out
#   0.00  nothing of yours             out
RELEVANT_THRESHOLD = 0.35


def is_relevant(relevance: Optional[Relevance]) -> bool:
    """
    Whether the "relevant to me" filter should keep this event.

    An unscored event (no profile) counts as relevant: the filter must never
    hide something because the user has not configured anything.
    """
    if relevance is None:
        return True
    return relevance.score >= RELEVANT_THRESHOLD
