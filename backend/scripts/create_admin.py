"""
backend/scripts/create_admin.py
Create the account you log in with.

There is no self-registration -- an intelligence dashboard that anyone can sign
up to is not one you would connect a social account to -- so the first user has
to be made deliberately. That was only possible through BOOTSTRAP_ADMIN_EMAIL
and BOOTSTRAP_ADMIN_PASSWORD, which meant editing .env and restarting before
you could see anything behind a login.

    cd backend
    python scripts/create_admin.py                       # prompts
    python scripts/create_admin.py --email you@x.com     # prompts for password only

This is the same account the dashboard uses to reach Settings, exposure
profiles, and the social sign-in fields. It has nothing to do with your social
media passwords -- those are stored separately, encrypted, and never travel to
any server.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email")
    parser.add_argument("--password", help="omit to be prompted (not echoed)")
    parser.add_argument("--force", action="store_true",
                        help="reset the password if the account already exists")
    args = parser.parse_args()

    from sqlalchemy import select

    from auth.bootstrap import init as auth_init
    from auth.db import session_scope
    from auth.models import User
    from auth.passwords import WeakPassword, hash_password

    # Creates the tables if this is a first run, so the script works on a fresh
    # checkout rather than requiring the server to have been started once.
    auth_init()

    email = (args.email or input("Email: ")).strip().lower()
    if not email or "@" not in email:
        print("A valid email address is required.")
        return 1

    password = args.password or getpass.getpass("Password: ")
    if not args.password:
        if password != getpass.getpass("Confirm: "):
            print("Passwords did not match.")
            return 1

    try:
        pw_hash = hash_password(password)
    except WeakPassword as exc:
        print(f"Rejected: {exc}")
        return 1

    with session_scope() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            if not args.force:
                print(f"{email} already exists. Re-run with --force to reset "
                      f"its password.")
                return 1
            existing.password_hash = pw_hash
            # Invalidates every issued token, which is the point of a reset.
            existing.token_version = (existing.token_version or 0) + 1
            print(f"Password reset for {email}. Existing sessions are now invalid.")
        else:
            db.add(User(email=email, password_hash=pw_hash,
                        role="admin", display_name="Owner"))
            print(f"Created admin {email}.")

    print("\nLog in at the dashboard, then open the ACCOUNTS tab to connect a "
          "social account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
