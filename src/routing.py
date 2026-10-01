"""بررسی خالص مسیر وب‌هوک و مسیر ثبت وب‌هوک، بدون شبکه.

مستند setWebhook بله فقط یک آدرس می‌گیرد (پورت ۴۴۳ یا ۸۸) و فیلد راز جدا ندارد.
برای همین WEBHOOK_SECRET را خودمان چک می‌کنیم: یا تکه‌ای از مسیر
(/webhook/<راز>) یا هدر X-Webhook-Secret.
اگر راز خالی باشد فقط خود /webhook باز است، تا توسعهٔ محلی گیر نکند.
"""

from __future__ import annotations

import hmac
from urllib.parse import unquote


def secrets_equal(left: str, right: str) -> bool:
    """مقایسهٔ راز بدون لو رفتن طول یا تفاوت زودهنگام. مقایسهٔ معمولی رشته این را تضمین نمی‌کند."""
    left_bytes = left.encode("utf-8")
    right_bytes = right.encode("utf-8")
    if len(left_bytes) != len(right_bytes):
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


def webhook_authorized(path: str, header_secret: str | None, configured_secret: str | None) -> bool:
    """می‌گوید این درخواست وب‌هوک مجاز است یا نه.

    مسیر اضافی بعد از راز رد می‌شود تا کسی با پسوند تصادفی وارد نشود.
    راز داخل مسیر ممکن است URL-encode شده باشد، برای همین قبل از مقایسه باز می‌شود.
    """
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
    """مسیر /set-webhook بدون WEBHOOK_SECRET بسته می‌ماند تا غریبه وب‌هوک را عوض نکند."""
    configured = (configured_secret or "").strip()
    if not configured:
        return False
    return secrets_equal(header_secret or "", configured)
