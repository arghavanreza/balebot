#!/usr/bin/env python3
"""Register this Worker's HTTPS URL with Bale.

Usage (from the repo root):

    export BALE_TOKEN=...
    export WEBHOOK_URL=https://<worker>/webhook
    # If WEBHOOK_SECRET is set, the URL must include it:
    #   https://<worker>/webhook/<WEBHOOK_SECRET>
    uv run python scripts/set_webhook.py

The script also reads `.dev.vars` or `.env` for any variable that is not
already in the environment. It never prints the token.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    _load_file(root / ".dev.vars")
    _load_file(root / ".env")

    token = os.environ.get("BALE_TOKEN", "").strip()
    url = os.environ.get("WEBHOOK_URL", "").strip()
    if not token or not url:
        print("Set BALE_TOKEN and WEBHOOK_URL.", file=sys.stderr)
        return 1
    if not url.startswith("https://"):
        print("WEBHOOK_URL must be https (Bale allows ports 443 and 88).", file=sys.stderr)
        return 1

    endpoint = f"https://tapi.bale.ai/bot{token}/setWebhook"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps({"url": url}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "bale-excel-bot/0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        status = exc.code
    print(f"HTTP {status}")
    print(body)
    return 0 if status < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
