"""Pure HTTP checks for the webhook and the setup route.

Bale's documented `setWebhook` only takes a URL (ports 443 or 88). There is
no secret-token parameter in the current docs, so `WEBHOOK_SECRET` is checked
either as a path segment (`/webhook/<secret>`) or as the `X-Webhook-Secret`
header. When the secret is unset, only the bare `/webhook` path is accepted.
"""

from __future__ import annotations

import hmac
from urllib.parse import unquote


def secrets_equal(left: str, right: str) -> bool:
    left_bytes = left.encode("utf-8")
    right_bytes = right.encode("utf-8")
    if len(left_bytes) != len(right_bytes):
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


def webhook_authorized(path: str, header_secret: str | None, configured_secret: str | None) -> bool:
    configured = (configured_secret or "").strip()
    normalized = path.rstrip("/") or "/"
    if not configured:
        return normalized == "/webhook"
    if normalized == "/webhook":
        return secrets_equal(header_secret or "", configured)
    prefix = "/webhook/"
    if normalized.startswith(prefix):
        rest = normalized[len(prefix) :]
        if not rest or "/" in rest:
            return False
        return secrets_equal(unquote(rest), configured)
    return False


def setup_authorized(header_secret: str | None, configured_secret: str | None) -> bool:
    """`/set-webhook` stays closed unless WEBHOOK_SECRET is configured."""
    configured = (configured_secret or "").strip()
    if not configured:
        return False
    return secrets_equal(header_secret or "", configured)
