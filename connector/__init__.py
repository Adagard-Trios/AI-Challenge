"""
Roger connector.

Runs on the user's own machine. Holds their social sessions locally, encrypted,
and collects from their own IP. The server receives collected posts and status;
it never receives a credential and has no way to obtain one.

That is not a policy -- it is structural. There is nowhere on the server for a
cookie to go (see backend/auth/models.py, and the test that fails if a
cookie-shaped column ever appears).

    python -m connector pair 123-456-789 --server https://...
    python -m connector connect linkedin
    python -m connector run "Sri Lanka economy"
"""

__version__ = "0.1.0"
