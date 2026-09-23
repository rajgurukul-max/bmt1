"""One-time-per-day helper to generate a Kite Connect access token.

Kite Connect access tokens expire daily. Run this each trading morning:

    python auth.py                    # prompts interactively for request_token
    python auth.py <request_token>    # non-interactive, e.g. when run by an agent

It prints a login URL, you log in in the browser, Zerodha redirects to your
configured redirect URL with a `request_token` query param — pass that back in
(as the CLI arg, or when prompted), and this script exchanges it for an access
token and writes it into `.env`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from kiteconnect import KiteConnect

from config import BASE_DIR, load_config


def _update_env_file(env_path: Path, key: str, value: str) -> None:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=")
    found = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    cfg = load_config()
    kite = KiteConnect(api_key=cfg.zerodha.api_key)

    if len(sys.argv) > 1:
        request_token = sys.argv[1].strip()
    else:
        print("Log in using this URL, then copy the `request_token` from the redirect:")
        print(kite.login_url())
        request_token = input("request_token: ").strip()

    session = kite.generate_session(request_token, api_secret=cfg.zerodha.api_secret)
    access_token = session["access_token"]

    env_path = BASE_DIR / ".env"
    _update_env_file(env_path, "KITE_ACCESS_TOKEN", access_token)
    print(f"Access token saved to {env_path}")


if __name__ == "__main__":
    main()
