"""
src/intelligence/taxonomy.py
Canonical names for the things events are about.

Relevance scoring is a join between what an event mentions and what a business
is exposed to. That join is only as good as the names on both sides agreeing:
if an event says "Port of Colombo" and a user's profile says "Colombo Port",
the match silently does not happen, the event is ranked low, and nobody ever
finds out. Under-matching is invisible in exactly the way this codebase keeps
being bitten by -- it looks like "not much happened today".

So canonicalisation is not a tidy-up step here, it is the feature. An LLM
extracting entities produces whatever surface form appeared in the text; this
module maps that onto one identity.

Deliberately a seed table plus normalisation, not fuzzy matching. Sri Lanka has
25 districts and a handful of ports and sectors -- a known, closed vocabulary
for the things that matter most. Fuzzy matching earns its keep on the open tail
(company names), where `normalise()` alone is the fallback and a miss costs a
weaker match rather than a wrong one.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, Tuple

# The entity types the extractor may emit. Closed on purpose: an open taxonomy
# produces a long tail of near-synonymous types that nothing can join on.
ENTITY_TYPES = ("PLACE", "ORG", "SECTOR", "INFRASTRUCTURE", "LANE")

# How an entity relates to the event. "affected" is what relevance cares about;
# an event where your district is the ACTOR (its council passed a bylaw) is
# different from one where it is AFFECTED (it flooded).
ENTITY_ROLES = ("affected", "actor", "mentioned")


# --- seed vocabulary -------------------------------------------------------

# All 25 administrative districts. Aliases cover the spellings and the
# "X District" form that news copy uses interchangeably.
DISTRICTS: Dict[str, Tuple[str, ...]] = {
    "Colombo": ("kolamba", "colombo district"),
    "Gampaha": ("gampaha district", "negombo"),
    "Kalutara": ("kalutara district", "panadura"),
    "Kandy": ("kandy district", "mahanuwara"),
    "Matale": ("matale district", "dambulla"),
    "Nuwara Eliya": ("nuwaraeliya", "nuwara-eliya", "nuwara eliya district"),
    "Galle": ("galle district",),
    "Matara": ("matara district",),
    "Hambantota": ("hambantota district",),
    "Jaffna": ("jaffna district", "yalpanam"),
    "Kilinochchi": ("kilinochchi district",),
    "Mannar": ("mannar district",),
    "Mullaitivu": ("mullaithivu", "mullaitivu district"),
    "Vavuniya": ("vavuniya district",),
    "Puttalam": ("puttalam district", "chilaw"),
    "Kurunegala": ("kurunegala district",),
    "Anuradhapura": ("anuradhapura district",),
    "Polonnaruwa": ("polonnaruwa district",),
    "Badulla": ("badulla district",),
    "Monaragala": ("moneragala", "monaragala district"),
    "Ratnapura": ("ratnapura district",),
    "Kegalle": ("kegalla", "kegalle district"),
    "Ampara": ("amparai", "ampara district"),
    "Batticaloa": ("batticaloa district", "madakalapuwa"),
    "Trincomalee": ("trincomalee district", "trinco"),
}

# Ports and the infrastructure a trade-exposed business actually depends on.
INFRASTRUCTURE: Dict[str, Tuple[str, ...]] = {
    "Port of Colombo": (
        "colombo port", "colombo harbour", "colombo harbor", "cmb port", "cmb",
        "port of colombo south", "colombo south harbour",
    ),
    "Port of Hambantota": ("hambantota port", "hambantota harbour", "hip"),
    "Port of Trincomalee": ("trincomalee port", "trinco port"),
    "Port of Galle": ("galle port", "galle harbour"),
    "Bandaranaike International Airport": (
        "bia", "katunayake airport", "colombo airport", "cmb airport",
    ),
    "Mattala Airport": ("mattala", "mria", "mattala rajapaksa airport"),
    "Southern Expressway": ("e01", "southern highway"),
    "Colombo-Katunayake Expressway": ("e03", "airport expressway"),
    "Central Expressway": ("e04",),
    "National Grid": ("ceb grid", "power grid", "electricity grid"),
}

# Sectors. Superset of economicalAgentNode.sectors, extended with the export
# sectors a Sri Lankan trade business is actually in.
SECTORS: Dict[str, Tuple[str, ...]] = {
    "apparel": ("garment", "garments", "textile", "textiles", "clothing"),
    "tea": ("ceylon tea", "plantation", "plantations"),
    "tourism": ("hospitality", "hotels", "travel"),
    "banking": ("banks", "bank", "financial services"),
    "finance": ("capital markets", "insurance"),
    "manufacturing": ("industry", "industrial", "factories"),
    "agriculture": ("farming", "paddy", "agri"),
    "technology": ("it", "ict", "software", "bpo"),
    "real estate": ("property", "construction"),
    "retail": ("wholesale", "supermarket", "fmcg"),
    "logistics": ("shipping", "freight", "transport", "haulage", "3pl"),
    "fisheries": ("fishing", "seafood"),
    "rubber": ("rubber products",),
    "spices": ("cinnamon", "pepper", "spice"),
}

# type -> {canonical: (aliases,)}
SEED_VOCABULARY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "PLACE": DISTRICTS,
    "INFRASTRUCTURE": INFRASTRUCTURE,
    "SECTOR": SECTORS,
}


def _build_lookup() -> Dict[str, Dict[str, str]]:
    """{type: {normalised surface form: canonical}}, built once at import."""
    lookup: Dict[str, Dict[str, str]] = {}
    for etype, entries in SEED_VOCABULARY.items():
        table: Dict[str, str] = {}
        for canonical, aliases in entries.items():
            table[normalise(canonical)] = canonical
            for alias in aliases:
                table[normalise(alias)] = canonical
        lookup[etype] = table
    return lookup


def normalise(name: str) -> str:
    """
    Reduce a surface form to a comparable key.

    Strips accents, lowercases, drops punctuation and collapses whitespace, then
    removes the corporate and administrative suffixes that differ between two
    mentions of the same thing ("Hayleys PLC" vs "Hayleys").
    """
    if not name:
        return ""

    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Trailing noise words that never distinguish two entities.
    text = re.sub(
        r"\b(plc|pvt|private|limited|ltd|inc|corporation|corp|company|co|"
        r"district|province|the)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


_LOOKUP = _build_lookup()


def canonicalise(name: str, entity_type: str) -> Tuple[str, bool]:
    """
    Map a surface form onto its canonical name.

    Returns (canonical_name, is_known). ``is_known`` is False for anything
    outside the seed vocabulary -- typically a company. Those are kept, keyed on
    their normalised form so two spellings still converge, but the caller can
    treat them with less confidence.
    """
    key = normalise(name)
    if not key:
        return "", False

    table = _LOOKUP.get((entity_type or "").upper(), {})
    if key in table:
        return table[key], True

    # A place or sector we do not know is more likely a bad extraction than a
    # 26th district, but it is not our job to discard it -- only to say so.
    return _titlecase(key), False


def _titlecase(key: str) -> str:
    """Presentable canonical form for an unknown entity."""
    return " ".join(w.capitalize() if len(w) > 2 else w.upper() for w in key.split())


def canonicalise_many(
    entities: Iterable[dict],
) -> list:
    """
    Canonicalise a batch of extracted entities, dropping unusable ones.

    Drops anything with no name, an unknown type, or a name so short it will
    match everything ("EU", "SL"). Two-letter tokens are the single biggest
    source of junk matches in a relevance join.
    """
    out = []
    seen = set()

    for raw in entities or []:
        if not isinstance(raw, dict):
            continue

        etype = str(raw.get("type", "")).upper().strip()
        if etype not in ENTITY_TYPES:
            continue

        name = str(raw.get("name", "")).strip()
        if len(normalise(name)) < 3:
            continue

        canonical, known = canonicalise(name, etype)
        if not canonical:
            continue

        role = str(raw.get("role", "mentioned")).lower().strip()
        if role not in ENTITY_ROLES:
            role = "mentioned"

        dedup_key = (etype, canonical)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        out.append({
            "type": etype,
            "name": canonical,
            "role": role,
            "known": known,
            "surface_form": name,
        })

    return out


def known_names(entity_type: str) -> Tuple[str, ...]:
    """Canonical names for a type, used to build UI pickers and prompts."""
    return tuple(SEED_VOCABULARY.get(entity_type.upper(), {}))
