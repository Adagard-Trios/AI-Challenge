"""
Social credentials, encrypted on the user's own machine.

The user asked for a username/password flow. The research on why personal
accounts get restricted says the risky act is LOGGING IN, not scraping: a login
from an unfamiliar fingerprint triggers device verification, repeated logins
trigger lockouts, and a fresh session every run is itself anomalous because a
real person's session lasts weeks.

So the password exists to pre-fill a form ONCE, in a real visible browser, with
the human completing any challenge. It is stored here so that is pleasant
rather than because automating login is safe -- it is not.

What these tests protect: the password never leaves the device, never reaches
the server, and never hits disk in the clear.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
REPO_ROOT = PROJECT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

pytest.importorskip("cryptography")


@pytest.fixture
def vault(tmp_path):
    from connector.vault import CredentialVault

    return CredentialVault(directory=tmp_path)


# --- round trip ------------------------------------------------------------

def test_saves_and_returns_credentials(vault):
    vault.save("linkedin", "ops@example.com", "correct horse battery staple")

    entry = vault.get("linkedin")
    assert entry["username"] == "ops@example.com"
    assert entry["password"] == "correct horse battery staple"


def test_platforms_are_independent(vault):
    vault.save("linkedin", "a@example.com", "pw-a")
    vault.save("twitter", "b@example.com", "pw-b")

    assert vault.get("linkedin")["password"] == "pw-a"
    assert vault.get("twitter")["password"] == "pw-b"
    assert sorted(vault.platforms()) == ["linkedin", "twitter"]


def test_saving_again_replaces_rather_than_duplicates(vault):
    vault.save("linkedin", "a@example.com", "old")
    vault.save("linkedin", "a@example.com", "new")

    assert vault.get("linkedin")["password"] == "new"
    assert vault.platforms() == ["linkedin"]


def test_forget_removes_only_that_platform(vault):
    vault.save("linkedin", "a@example.com", "pw-a")
    vault.save("twitter", "b@example.com", "pw-b")

    assert vault.forget("linkedin") is True
    assert vault.get("linkedin") is None
    assert vault.get("twitter") is not None

    assert vault.forget("linkedin") is False


def test_unknown_platform_is_rejected(vault):
    with pytest.raises(ValueError):
        vault.save("myspace", "a", "b")


def test_blank_credentials_are_rejected(vault):
    with pytest.raises(ValueError):
        vault.save("linkedin", "", "pw")
    with pytest.raises(ValueError):
        vault.save("linkedin", "user", "")


# --- the security properties ----------------------------------------------

def test_the_password_never_hits_disk_in_the_clear(vault, tmp_path):
    """The whole point of encrypting it."""
    secret = "S3cret-Passw0rd-Do-Not-Leak"
    vault.save("linkedin", "ops@example.com", secret)

    for path in tmp_path.rglob("*"):
        if path.is_file():
            blob = path.read_bytes()
            assert secret.encode() not in blob, f"password readable in {path.name}"
            assert b"ops@example.com" not in blob, f"username readable in {path.name}"


def test_a_tampered_vault_fails_loudly_rather_than_returning_nothing(vault):
    """
    A corrupt vault that read as empty would send the user round the "why
    won't it remember me" loop with no error anywhere.
    """
    vault.save("linkedin", "ops@example.com", "pw")

    blob = bytearray(vault.path.read_bytes())
    blob[-1] ^= 0xFF
    vault.path.write_bytes(bytes(blob))

    with pytest.raises(Exception):
        vault.get("linkedin")


def test_describe_never_returns_passwords(vault):
    """Used to render the UI list; must not be a leak path."""
    vault.save("linkedin", "ops@example.com", "hunter2")

    described = vault.describe()
    assert described == {"linkedin": "ops@example.com"}
    assert "hunter2" not in json.dumps(described)


def test_an_absent_vault_is_empty_not_an_error(vault):
    assert vault.platforms() == []
    assert vault.describe() == {}
    assert vault.get("linkedin") is None


# --- the server must never receive one ------------------------------------

def test_no_backend_endpoint_accepts_a_social_password():
    """
    The architectural promise. If a route ever starts accepting one, the
    credential stops being device-local and the whole design changes.
    """
    import re

    routes = (PROJECT_ROOT / "auth" / "routes.py").read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")

    for name, source in (("auth/routes.py", routes), ("main.py", main)):
        code = "\n".join(
            line for line in source.splitlines()
            if not line.strip().startswith("#")
        )
        # A social password field on a request model would look like this.
        offenders = re.findall(
            r"(social_password|platform_password|instagram_password|"
            r"linkedin_password|facebook_password|twitter_password)",
            code,
        )
        assert not offenders, (
            f"{name} accepts a social account password: {set(offenders)}. "
            "Credentials are device-local by design."
        )


def test_the_connector_never_sends_credentials_upstream():
    """
    The vault is read only by the local login flow. If it ever appears in the
    push path, a password could leave the machine.
    """
    push_surfaces = [
        REPO_ROOT / "connector" / "collect.py",
        REPO_ROOT / "connector" / "storage.py",
    ]
    for path in push_surfaces:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "CredentialVault" not in source, (
            f"{path.name} touches the credential vault; only the local login "
            "flow should"
        )


# --- pre-fill stops where a human must take over --------------------------

def test_prefill_does_not_submit_the_form_or_answer_challenges():
    """
    Automating past a device-verification challenge is what turns a routine
    prompt into a lockout, and the challenge exists to prove a person is
    present. Filling two fields is the whole job.
    """
    import inspect

    from connector import connect

    source = inspect.getsource(connect._prefill_login)
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )

    for forbidden in ("click(", "press(", "submit", "keyboard"):
        assert forbidden not in code, (
            f"_prefill_login uses {forbidden!r} -- it must fill the fields and "
            "stop, leaving submission and 2FA to the user"
        )


def test_every_supported_platform_has_login_field_selectors():
    from connector.connect import LOGIN_FIELDS, LOGIN_URLS

    missing = set(LOGIN_URLS) - set(LOGIN_FIELDS)
    assert not missing, f"no pre-fill selectors for {sorted(missing)}"
