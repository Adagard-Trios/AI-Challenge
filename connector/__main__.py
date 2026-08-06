"""
connector CLI

    python -m connector pair 123-456-789 --server https://roger-backend.onrender.com
    python -m connector connect linkedin
    python -m connector status
    python -m connector collect "Sri Lanka economy"
    python -m connector run "Sri Lanka economy"
    python -m connector disconnect linkedin
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .collect import Collector
from .vault import CredentialVault
from .connect import connect_via_login, connect_via_paste, disconnect
from .storage import DeviceConfig, SessionStore, config_dir

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("connector")

PLATFORMS = ("twitter", "facebook", "instagram", "linkedin")


def cmd_pair(args) -> int:
    import requests

    server = args.server.rstrip("/")
    try:
        response = requests.post(
            f"{server}/api/connector/claim",
            json={"pair_code": args.code.strip(), "device_name": args.name},
            timeout=30,
        )
    except requests.RequestException as exc:
        print(f"Could not reach {server}: {exc}")
        return 1

    if response.status_code != 200:
        print(f"Pairing failed: {response.status_code} {response.text}")
        return 1

    data = response.json()
    DeviceConfig().save(
        server_url=server,
        device_token=data["device_token"],
        device_id=data["device_id"],
        user_id=data["user_id"],
    )
    print(f"\nPaired with {server}.")
    print(f"Config: {config_dir()}")
    print("\nNext: connect an account, e.g.  python -m connector connect linkedin")
    return 0


def cmd_connect(args) -> int:
    try:
        if args.paste:
            raw = sys.stdin.read() if args.paste == "-" else open(args.paste, encoding="utf-8").read()
            summary = connect_via_paste(args.platform, raw)
        else:
            # Credentials, if the user saved any, come from the LOCAL vault --
            # they are never fetched from the server and never sent to it.
            prefill = None
            if not getattr(args, "no_prefill", False):
                try:
                    prefill = CredentialVault().get(args.platform)
                except Exception as exc:
                    print(f"  (could not read saved credentials: {exc})")
            summary = connect_via_login(args.platform, prefill=prefill)
    except Exception as exc:
        print(f"\nCould not connect {args.platform}: {exc}")
        return 1

    print(f"\n{args.platform} connected." + (f"  ({summary['handle']})" if summary.get("handle") else ""))
    return 0


def cmd_credentials(args) -> int:
    """
    Manage the local credential vault.

    The password is read from a hidden prompt, encrypted with the same
    AES-256-GCM key as the session store, and written to this machine only. It
    is never transmitted anywhere -- the server has no endpoint that accepts
    one, by design.
    """
    import getpass

    vault = CredentialVault()

    if args.action == "list":
        saved = vault.describe()
        if not saved:
            print("No credentials saved on this machine.")
            return 0
        print("Saved on this machine (passwords not shown):")
        for platform, username in sorted(saved.items()):
            print(f"  {platform:<10} {username}")
        return 0

    if not args.platform:
        print(f"Which platform? e.g. `credentials {args.action} linkedin`")
        return 1

    if args.action == "forget":
        removed = vault.forget(args.platform)
        print(f"{args.platform}: {'removed' if removed else 'nothing saved'}")
        return 0

    print(f"\nSaving {args.platform} credentials on THIS machine only.")
    print("They are encrypted at rest and never sent to the server.")
    print("You will still complete 2FA yourself in the browser window.\n")

    username = input(f"  {args.platform} username or email: ").strip()
    password = getpass.getpass(f"  {args.platform} password (hidden): ")

    try:
        vault.save(args.platform, username, password)
    except Exception as exc:
        print(f"\nCould not save: {exc}")
        return 1

    print(f"\nSaved. Run `python -m connector connect {args.platform}` to sign in.")
    return 0


def cmd_disconnect(args) -> int:
    return 0 if disconnect(args.platform) else 1


def cmd_status(args) -> int:
    store = SessionStore()
    device = DeviceConfig()
    cfg = device.load()

    print(f"\nConfig directory : {config_dir()}")
    print(f"Server           : {cfg.get('server_url') or 'not paired'}")
    print(f"Paired           : {'yes' if device.is_paired else 'no'}")
    print("\nConnected accounts:")

    connected = store.available()
    if not connected:
        print("  (none)   ->  python -m connector connect linkedin")
    else:
        collector = Collector(store, device)
        for platform in connected:
            cred = collector.credential_for(platform)
            if cred is None:
                print(f"  {platform:11s} unreadable (wrong key?)")
                continue
            expiry = cred.expires_at.date().isoformat() if cred.expires_at else "unknown"
            flag = "EXPIRED" if cred.is_expired else "ok"
            handle = f" {cred.handle}" if cred.handle else ""
            print(f"  {platform:11s} {flag:8s} expires {expiry}{handle}")

    print("\nSessions are encrypted on this machine and are never uploaded.")
    return 0


def cmd_collect(args) -> int:
    results = Collector().collect_all(args.query, args.max_items)
    if not results:
        print("No connected accounts. Run:  python -m connector connect linkedin")
        return 1
    print(json.dumps(results, indent=2))
    return 0 if all(r.get("status") in ("ok", "budget_exhausted") for r in results) else 1


def cmd_run(args) -> int:
    try:
        Collector().run_forever(args.query, args.interval, args.max_items)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="connector",
        description="Collects social posts from your own machine. "
                    "Session cookies stay here and are never uploaded.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="pair with the server using a code from the dashboard")
    pair.add_argument("code")
    pair.add_argument("--server", required=True)
    pair.add_argument("--name", default="connector")
    pair.set_defaults(func=cmd_pair)

    conn = sub.add_parser("connect", help="connect a social account")
    conn.add_argument("platform", choices=PLATFORMS)
    conn.add_argument("--paste", metavar="FILE",
                      help="load a storage_state JSON instead of opening a browser ('-' for stdin)")
    conn.add_argument("--no-prefill", action="store_true",
                      help="do not pre-fill saved credentials")
    conn.set_defaults(func=cmd_connect)

    cred = sub.add_parser(
        "credentials",
        help="save social logins on THIS machine so connect can pre-fill them",
    )
    cred.add_argument("action", choices=["set", "list", "forget"])
    cred.add_argument("platform", nargs="?", choices=PLATFORMS)
    cred.set_defaults(func=cmd_credentials)

    dis = sub.add_parser("disconnect", help="remove a local session")
    dis.add_argument("platform", choices=PLATFORMS)
    dis.set_defaults(func=cmd_disconnect)

    st = sub.add_parser("status", help="show pairing and connected accounts")
    st.set_defaults(func=cmd_status)

    col = sub.add_parser("collect", help="collect once and push")
    col.add_argument("query")
    col.add_argument("--max-items", type=int, default=20)
    col.set_defaults(func=cmd_collect)

    run = sub.add_parser("run", help="collect on a loop")
    run.add_argument("query")
    run.add_argument("--interval", type=int, default=900)
    run.add_argument("--max-items", type=int, default=20)
    run.set_defaults(func=cmd_run)

    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
