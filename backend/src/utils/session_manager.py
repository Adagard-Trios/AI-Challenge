import os
import time
import json
import logging
from playwright.sync_api import sync_playwright

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("SessionManager")

# Configuration
SESSIONS_DIR = ".sessions"
USER_DATA_DIR = ".browser_data"  # Folder to store actual browser profile data

# Platform Configuration Mapping
PLATFORMS = {
    "twitter": {
        "name": "Twitter/X",
        "login_url": "https://twitter.com/i/flow/login",
        "domain": "twitter.com",
    },
    "facebook": {
        "name": "Facebook",
        "login_url": "https://www.facebook.com/login",
        "domain": "facebook.com",
    },
    "linkedin": {
        "name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "domain": "linkedin.com",
    },
    "reddit": {
        "name": "Reddit",
        "login_url": "https://old.reddit.com/login",  # Default to Old Reddit for easier login
        "domain": "reddit.com",
    },
    "instagram": {
        "name": "Instagram",
        "login_url": "https://www.instagram.com/accounts/login/",
        "domain": "instagram.com",
    },
}


def ensure_dirs():
    """Creates necessary directories."""
    if not os.path.exists(SESSIONS_DIR):
        os.makedirs(SESSIONS_DIR)
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)


def create_session(platform_key: str):
    """
    Launches a Persistent Browser Context.
    - Uses FIREFOX for Reddit (bypasses Google-focused bot detection).
    - Uses CHROMIUM for others (standard compatibility).
    """
    platform = PLATFORMS.get(platform_key)
    if not platform:
        logger.error(f"Platform '{platform_key}' not found.")
        return

    ensure_dirs()
    session_file = os.path.join(SESSIONS_DIR, f"{platform_key}_storage_state.json")
    platform_user_data = os.path.join(USER_DATA_DIR, platform_key)

    logger.info(f"Starting Persistent Session for {platform['name']}...")

    with sync_playwright() as p:
        # ---------------------------------------------------------
        # STRATEGY 1: REDDIT (Use Firefox + Old Reddit)
        # ---------------------------------------------------------
        if platform_key == "reddit":
            logger.info("Using Firefox Engine (Best for Reddit evasion)...")
            context = p.firefox.launch_persistent_context(
                user_data_dir=platform_user_data,
                headless=False,
                viewport={"width": 1280, "height": 720},
                # Use a standard Firefox User Agent
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            )

        # ---------------------------------------------------------
        # STRATEGY 2: OTHERS (Use Chromium + Stealth Args)
        # ---------------------------------------------------------
        else:
            logger.info("Using Chromium Engine (Standard)...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=platform_user_data,
                headless=False,
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--disable-browser-side-navigation",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )

        # Apply Anti-Detection Script (Removes 'navigator.webdriver' property)
        page = context.pages[0] if context.pages else context.new_page()
        page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """
        )

        try:
            logger.info(f"Navigating to {platform['login_url']}...")
            page.goto(platform["login_url"], wait_until="domcontentloaded")

            # Interactive Loop
            print("\n" + "=" * 50)
            print(f"ACTION REQUIRED: Log in to {platform['name']} manually.")

            if platform_key == "reddit":
                print(
                    ">> You are on 'Old Reddit'. The login box is on the right-hand side."
                )
                print(
                    ">> Once logged in, it might redirect you to New Reddit. That is fine."
                )

            print("=" * 50 + "\n")

            input(
                f"Press ENTER here ONLY after you see the {platform['name']} Home Feed... "
            )

            # Save State
            logger.info("Capturing storage state...")
            context.storage_state(path=session_file)

            # Verify file
            if os.path.exists(session_file):
                size = os.path.getsize(session_file)
                logger.info(f"SUCCESS: Session saved to {session_file} ({size} bytes)")
            else:
                logger.error("Failed to save session file.")

        except Exception as e:
            logger.error(f"An error occurred: {e}")
        finally:
            context.close()


def list_sessions():
    ensure_dirs()
    files = [f for f in os.listdir(SESSIONS_DIR) if f.endswith("_storage_state.json")]
    if not files:
        print("No sessions found.")
    else:
        print(f"Found {len(files)} active sessions:")
        for f in files:
            print(f" - {f}")


if __name__ == "__main__":
    while True:
        print("\n--- Roger Session Manager (Stealth Mode) ---")
        print("1. Create/Refresh Twitter Session")
        print("2. Create/Refresh Facebook Session")
        print("3. Create/Refresh LinkedIn Session")
        print("4. Create/Refresh Reddit Session")
        print("5. Create/Refresh Instagram Session")
        print("6. List Saved Sessions")
        print("q. Quit")

        choice = input("Select an option: ").strip().lower()

        if choice == "1":
            create_session("twitter")
        elif choice == "2":
            create_session("facebook")
        elif choice == "3":
            create_session("linkedin")
        elif choice == "4":
            create_session("reddit")
        elif choice == "5":
            create_session("instagram")
        elif choice == "6":
            list_sessions()
        elif choice == "q":
            break
        else:
            print("Invalid option.")
