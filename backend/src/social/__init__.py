"""
src/social
Social account connection, driven from the web dashboard.

WHAT CHANGED AND WHY
--------------------
Collection used to require a separate `connector` process: pair it with a code,
run `python -m connector credentials linkedin` to type a password into a
terminal, then `python -m connector connect linkedin`. That separation existed
for one reason -- when the server is a shared free-tier host, a password sent to
it is a password sitting on someone else's machine, and session cookies there
are cookies you do not control.

Hosting from your own laptop removes that reason entirely. The "server" and
"the user's machine" are the same computer, so the process boundary was buying
nothing while costing a terminal, a pairing step, and a CLI.

So this module puts the same capability behind the dashboard. It is a merge,
not a rewrite: it imports the connector's own CredentialVault and SessionStore
and writes the same files, so `python -m connector status` still sees accounts
connected from the web UI and vice versa. One store, two front doors.

WHAT IS DELIBERATELY UNCHANGED
------------------------------
The properties that keep an account working are not conveniences and are not
relaxed here:

  * the password is encrypted at rest (AES-256-GCM, OS keychain)
  * it PRE-FILLS the platform's own login form and stops -- no auto-submit,
    no captcha solving, no 2FA automation. A human finishes the login.
  * a challenge stops that account until a person resumes it
  * daily request budgets and exponential backoff still apply
  * rotated cookies are written back after every run

Automating past a device-verification prompt is what turns a routine challenge
into a lockout. That is still true when the code lives in the backend.

THE ONE REAL TRADE-OFF, STATED PLAINLY
--------------------------------------
The password now travels from the browser to the backend over HTTP. On
localhost that is a loopback hop on your own machine. Over a tunnel it is a
password crossing the internet, so it requires HTTPS and AUTH_ENFORCED=1 --
scripts/serve_public.py refuses to start without both.

And the browser opens on the machine running the server, not on the machine
running the browser. For a laptop demo that is the same computer. For a remote
visitor it is not, which is why the UI says so rather than leaving it to be
discovered.
"""

from .service import (  # noqa: F401
    SUPPORTED_PLATFORMS,
    SocialService,
    get_service,
)
