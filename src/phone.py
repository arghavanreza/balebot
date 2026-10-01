"""نرمال‌کردن شمارهٔ موبایل ایران.

بازو هم دکمهٔ request_contact بله را می‌پذیرد و هم متنی که کاربر تایپ می‌کند.
هر دو به یک شکل +989XXXXXXXXX ذخیره می‌شوند تا در پیام مدیر و در D1 یکی باشند.
اعتبارسنجی عمداً سبک است: پیش‌شماره و تعداد رقم، نه تعلق شماره به اپراتور.
"""

from __future__ import annotations

import re

# ارقام فارسی و عربی را به لاتین برمی‌گردانیم تا ۰۹۱۲ و 0912 یکی شوند.
_DIGIT_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# فاصله، خط تیره و پرانتز را برمی‌داریم. خود رقم‌ها و + می‌مانند.
_SEPARATORS = re.compile(r"[\s\u200c\u200d().\-]")
# بعد از برداشتن پیش‌شماره، موبایل ایران ده رقم است و با ۹ شروع می‌شود.
_MOBILE = re.compile(r"9\d{9}")


def normalize_phone(value: object) -> str | None:
    """شماره را به +989 و ده رقم تبدیل می‌کند. شکل ناشناس یعنی None، نه خطا.

    پذیرفته می‌شود: 0912…، 912…، 98912…، +98912…، 0098912… با ارقام فارسی یا عربی.
    تلفن ثابت (مثلاً ۰۲۱) رد می‌شود چون رقم بعد از صفر، ۹ نیست.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None

    text = text.translate(_DIGIT_FOLD)
    text = _SEPARATORS.sub("", text.strip())
    if text.startswith("+"):
        text = text[1:]
    # ۰۰ قبل از ۹۸ همان پیش‌شمارهٔ بین‌المللی است.
    if text.startswith("0098"):
        text = text[4:]
    elif text.startswith("98"):
        text = text[2:]
    elif text.startswith("0"):
        text = text[1:]

    if _MOBILE.fullmatch(text) is None:
        return None
    return "+98" + text
