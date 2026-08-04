"""
src/scrapers
Consolidated social scrapers.

Replaces three near-duplicate implementations of the same eight scrapers, which
lived in src/utils/utils.py, src/utils/profile_scrapers.py and
src/utils/tool_factory.py. The copies drifted: the ones that actually executed
(tool_factory's, reached via create_tool_set) were the weakest, and the best
code in the repo -- the Twitter profile scraper with retries, engagement
extraction and a search fallback -- never ran at all.

Layout:
    hygiene.py      launch profiles, UA strings, pacing constants, daily budgets
    challenge.py    expired / challenged / logged-in classification
    credentials.py  the single seam for obtaining a session
    text.py         post-text cleaners (previously duplicated up to 7x)
    base.py         the one browser launch site; pacing and health enforcement

Scrapers are plain functions taking a ScrapeContext, not @tool-decorated.
Decorating at the implementation layer is what forced the duplication in the
first place: the tool layer wraps these rather than reimplementing them.
"""

from .base import (
    BudgetExhausted,
    ScrapeContext,
    ScrapeResult,
    browser_session,
    reset_budgets,
    run_scrape,
)
from .challenge import (
    ChallengeDetected,
    SessionExpired,
    SessionState,
    classify,
    enforce,
    probe,
)
from .credentials import (
    PLATFORMS,
    CredentialError,
    FileCredentialStore,
    NullCredentialStore,
    SocialCredential,
    derive_expiry,
    filter_first_party,
    get_credential,
    get_credential_store,
    missing_required,
    set_credential_store,
    validate,
)
from .hygiene import LaunchProfile, budget_for
from .text import (
    clean_fb_text,
    clean_linkedin_text,
    extract_media_id_instagram,
    fetch_caption_via_private_api,
)

__all__ = [
    # base
    "BudgetExhausted", "ScrapeContext", "ScrapeResult", "browser_session",
    "reset_budgets", "run_scrape",
    # challenge
    "ChallengeDetected", "SessionExpired", "SessionState",
    "classify", "enforce", "probe",
    # credentials
    "PLATFORMS", "CredentialError", "FileCredentialStore", "NullCredentialStore",
    "SocialCredential", "derive_expiry", "filter_first_party", "get_credential",
    "get_credential_store", "missing_required", "set_credential_store", "validate",
    # hygiene
    "LaunchProfile", "budget_for",
    # text
    "clean_fb_text", "clean_linkedin_text",
    "extract_media_id_instagram", "fetch_caption_via_private_api",
]
