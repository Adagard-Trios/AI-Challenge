"""
src/intelligence/exposure_routes.py
What this business depends on.

One profile per user. The existing intel_config.json is a single shared file,
so putting exposure there would give every account the same exposure and defeat
the point of scoring relevance per business.

On anonymous callers: require_user returns None when AUTH_ENFORCED=0, which is
the default and is what lets the pre-existing routes work before the frontend
sends tokens. There is no honest way to store "this user's exposure" without a
user, so these endpoints say so rather than quietly writing to a shared row.
The feed degrades correctly in that case -- relevance is null and the order is
unchanged, which is the same path a signed-in user with an empty profile takes.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.db import get_db
from auth.dependencies import require_user

from .models import ExposureProfile
from .taxonomy import canonicalise, known_names

logger = logging.getLogger("exposure")

router = APIRouter(prefix="/api/exposure", tags=["exposure"])

# A profile is a form, not a corpus. These caps stop a paste-bomb from turning
# every feed request into a thousand-term scan.
MAX_ITEMS_PER_FIELD = 100
MAX_ITEM_LENGTH = 120


class ExposurePayload(BaseModel):
    districts: List[str] = Field(default_factory=list)
    infrastructure: List[str] = Field(default_factory=list)
    lanes: List[str] = Field(default_factory=list)
    sectors: List[str] = Field(default_factory=list)
    suppliers: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


def _require_identified_user(user):
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "An exposure profile belongs to a user. Sign in to set one -- "
                "until then the feed is shown unranked."
            ),
        )
    return user


def _clean(values: List[str], *, entity_type: Optional[str] = None) -> List[str]:
    """
    Trim, cap, de-duplicate, and canonicalise where the taxonomy knows better.

    Canonicalising on the way IN is what makes the join work. A user typing
    "Colombo Port" must be stored as "Port of Colombo", because that is what
    the extractor produces on the event side -- otherwise the two never meet
    and the profile silently matches nothing.
    """
    out: List[str] = []
    seen = set()

    for raw in (values or [])[:MAX_ITEMS_PER_FIELD]:
        text = str(raw).strip()[:MAX_ITEM_LENGTH]
        if not text:
            continue

        if entity_type:
            canonical, _known = canonicalise(text, entity_type)
            text = canonical or text

        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)

    return out


def _normalise_payload(payload: ExposurePayload) -> dict:
    return {
        "districts": _clean(payload.districts, entity_type="PLACE"),
        "infrastructure": _clean(payload.infrastructure, entity_type="INFRASTRUCTURE"),
        "sectors": _clean(payload.sectors, entity_type="SECTOR"),
        # Lanes and suppliers are open sets -- no canonical vocabulary to snap
        # to, so they are stored as typed and normalised only at match time.
        "lanes": _clean(payload.lanes),
        "suppliers": _clean(payload.suppliers),
        "keywords": _clean(payload.keywords),
    }


def get_profile(db: Session, user_id: str) -> Optional[ExposureProfile]:
    return (
        db.query(ExposureProfile).filter_by(user_id=user_id).one_or_none()
    )


@router.get("")
def read_exposure(user=Depends(require_user), db: Session = Depends(get_db)):
    """This user's profile, plus the vocabulary the UI offers as choices."""
    user = _require_identified_user(user)
    profile = get_profile(db, user.id)

    return {
        "profile": profile.as_dict() if profile else ExposurePayload().model_dump(),
        "configured": bool(profile and not profile.is_empty()),
        # Pickers are built from the same seed vocabulary the extractor
        # canonicalises to, so a user cannot choose a value events can never
        # match.
        "vocabulary": {
            "districts": list(known_names("PLACE")),
            "infrastructure": list(known_names("INFRASTRUCTURE")),
            "sectors": list(known_names("SECTOR")),
        },
    }


@router.put("")
def write_exposure(
    payload: ExposurePayload,
    user=Depends(require_user),
    db: Session = Depends(get_db),
):
    """Replace this user's profile. Idempotent."""
    user = _require_identified_user(user)
    fields = _normalise_payload(payload)

    profile = get_profile(db, user.id)
    if profile is None:
        profile = ExposureProfile(user_id=user.id, **fields)
        db.add(profile)
    else:
        for key, value in fields.items():
            setattr(profile, key, value)

    db.commit()
    db.refresh(profile)

    logger.info(
        "[exposure] %s updated: %d districts, %d infrastructure, %d suppliers",
        user.id, len(fields["districts"]), len(fields["infrastructure"]),
        len(fields["suppliers"]),
    )

    return {
        "profile": profile.as_dict(),
        "configured": not profile.is_empty(),
    }


@router.delete("")
def clear_exposure(user=Depends(require_user), db: Session = Depends(get_db)):
    """Back to the unranked feed."""
    user = _require_identified_user(user)
    profile = get_profile(db, user.id)
    if profile is not None:
        db.delete(profile)
        db.commit()
    return {"profile": ExposurePayload().model_dump(), "configured": False}
