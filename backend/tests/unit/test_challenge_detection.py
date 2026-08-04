"""
Tests for src/scrapers/challenge.py

The detection this replaces was one expression, repeated at eight sites:

    "login" in page.url

Every test below marked REGRESSION would have been answered wrongly by that.
Getting these wrong is what turns a soft block into a banned account.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scrapers.challenge import (  # noqa: E402
    SIGNALS,
    SessionState,
    classify,
)


# --- REGRESSION: challenge walls the old check could not see ---------------

@pytest.mark.parametrize("platform,url", [
    ("twitter",   "https://x.com/account/access"),
    ("linkedin",  "https://www.linkedin.com/checkpoint/challenge/AgH123"),
    ("facebook",  "https://www.facebook.com/checkpoint/1501092823525282/"),
    ("instagram", "https://www.instagram.com/challenge/AbCdEf/"),
])
def test_challenge_paths_detected(platform, url):
    """
    REGRESSION. None of these URLs contain "login", so the old check read them
    as a healthy page and kept scraping an already-flagged account.
    """
    assert classify(platform, url) is SessionState.CHALLENGED


@pytest.mark.parametrize("platform,marker", [
    ("twitter",   "Suspicious login prevented"),
    ("linkedin",  "Let's do a quick security check"),
    ("facebook",  "You're temporarily blocked"),
    ("instagram", "Please wait a few minutes before you try again"),
])
def test_challenge_text_detected(platform, marker):
    """Soft blocks are served at a normal URL with an interstitial body."""
    html = f"<html><body><h2>{marker}</h2></body></html>"
    assert classify(platform, "https://example.com/feed", html) is SessionState.CHALLENGED


def test_challenge_text_matches_across_newlines_and_case():
    """Real markup wraps and cases inconsistently; matching must survive that."""
    body = "<div>\n  You're   TEMPORARILY\n  Blocked\n</div>"
    assert classify("facebook", "https://facebook.com/x", body) is SessionState.CHALLENGED


# --- REGRESSION: challenge must win over expiry ----------------------------

def test_challenge_takes_precedence_over_expiry():
    """
    REGRESSION, and the most consequential ordering in the module.

    A checkpoint page often ALSO shows a login form. Classifying it as EXPIRED
    would tell the user to reconnect -- feeding freshly captured credentials
    straight into a session the platform has already flagged.
    """
    html = '<form><input name="pass"></form><div>Please confirm it\'s you</div>'
    state = classify("facebook", "https://www.facebook.com/checkpoint/123", html,
                     present_selectors=['input[name="pass"]'])
    assert state is SessionState.CHALLENGED


# --- expiry ----------------------------------------------------------------

@pytest.mark.parametrize("platform,url", [
    ("twitter",   "https://x.com/i/flow/login"),
    ("linkedin",  "https://www.linkedin.com/authwall?trk=x"),
    ("facebook",  "https://www.facebook.com/login.php?next=y"),
    ("instagram", "https://www.instagram.com/accounts/login/"),
])
def test_expired_paths_detected(platform, url):
    assert classify(platform, url) is SessionState.EXPIRED


def test_expired_by_selector():
    state = classify("twitter", "https://x.com/home", "",
                     present_selectors=['[data-testid="loginButton"]'])
    assert state is SessionState.EXPIRED


# --- REGRESSION: false positive on a legitimate URL ------------------------

def test_post_url_containing_login_is_not_expired():
    """
    REGRESSION. `"login" in page.url` fired on any post whose URL merely
    contained the substring -- e.g. an article about a login outage -- marking
    a perfectly good session dead.
    """
    state = classify(
        "twitter",
        "https://x.com/someone/status/123?ref=login-outage-thread",
        "",
        present_selectors=['[data-testid="primaryColumn"]'],
    )
    assert state is SessionState.OK


def test_query_string_cannot_trigger_path_match():
    """Path-only matching: a redirect target in the query must not count."""
    state = classify(
        "facebook",
        "https://www.facebook.com/feed?next=/login.php",
        "",
        present_selectors=['div[role="banner"]'],
    )
    assert state is SessionState.OK


# --- REGRESSION: 200 OK logged-out page ------------------------------------

def test_logged_out_200_page_is_not_ok():
    """
    REGRESSION. All four platforms increasingly serve a 200 OK logged-out page
    at the URL you asked for, rather than redirecting. Absence of a login URL
    is therefore NOT evidence of a live session -- which is why a positive
    assertion is required.
    """
    html = "<html><body><div>Some public preview content</div></body></html>"
    assert classify("linkedin", "https://www.linkedin.com/feed/", html) is SessionState.UNKNOWN


@pytest.mark.parametrize("platform,selector", [
    ("twitter",   '[data-testid="SideNav_AccountSwitcher_Button"]'),
    ("linkedin",  ".global-nav__me"),
    ("facebook",  '[aria-label="Your profile"]'),
    ("instagram", 'svg[aria-label="Home"]'),
])
def test_positive_assertion_yields_ok(platform, selector):
    assert classify(platform, "https://example.com/feed", "",
                    present_selectors=[selector]) is SessionState.OK


# --- structure -------------------------------------------------------------

def test_unknown_platform_is_unknown_not_crash():
    assert classify("myspace", "https://myspace.com") is SessionState.UNKNOWN


def test_every_platform_declares_a_positive_assertion():
    """
    Without a logged_in selector a platform can only ever reach UNKNOWN, which
    silently disables health checking for it.
    """
    for platform, sig in SIGNALS.items():
        assert sig.logged_in_selectors, f"{platform} has no positive logged-in assertion"


def test_all_selectors_deduplicates():
    for platform, sig in SIGNALS.items():
        sels = sig.all_selectors()
        assert len(sels) == len(set(sels)), f"{platform} has duplicate selectors"


def test_empty_inputs_do_not_crash():
    assert classify("twitter", "", "", None) is SessionState.UNKNOWN
    assert classify("twitter", "not a url", None) is SessionState.UNKNOWN
