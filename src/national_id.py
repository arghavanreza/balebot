"""نام کامل مشتری و کد ملی، برای ثبت‌نام پیش از خدمات.

رقم کنترل کد ملی همان تابع transfer.with_national_check است تا دو فرمول در مخزن نماند.
وزن رقم اول ۱۰ است و رقم نهم ۲. باقی‌ماندهٔ ۱۱ اگر کمتر از ۲ باشد خودش رقم کنترل است.
رقم‌های یکسان مثل ۱۱۱۱۱۱۱۱۱۱ از نظر حساب گاهی درست درمی‌آیند ولی شناسهٔ واقعی نیستند.
این ماژول به بله و پایگاه وصل نیست.
"""

from __future__ import annotations

import re

from transfer import parse_national_id, with_national_check

# نام: حرف فارسی یا لاتین، و نیم‌فاصله داخل یک بخش (مثل علی‌رضا).
_NAME_WORD = re.compile(r"^[\u0600-\u06FFa-zA-Z\u200c]+$")


def national_id_check_digit(first9: str) -> str:
    """رقم دهم را از نه رقم اول می‌سازد. برای نمونه و تست است."""
    return with_national_check(first9)[9]


def normalize_national_id(value: object) -> str | None:
    """کد ملی را به ده رقم لاتین تبدیل می‌کند. شکل غلط یا رقم کنترل غلط یعنی None.

    خالی برای ثبت‌نام کافی نیست، برخلاف ستون اختیاری ذینفع در اکسل.
    فاصله و خط تیره نادیده گرفته می‌شوند. حرف اضافه رد می‌شود تا شبا با کد ملی قاطی نشود.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        return None
    if not text.strip():
        return None
    code, error = parse_national_id(text)
    if error or not code:
        return None
    return code


def parse_full_name(value: object) -> str | None:
    """نام و نام خانوادگی را از یک پیام برمی‌گرداند.

    حداقل دو بخش لازم است تا اسم کوچکِ تنها ذخیره نشود.
    هر بخش حداقل دو حرف است. رقم پذیرفته نمی‌شود.
    """
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if len(text) < 5 or len(text) > 80:
        return None
    parts = text.split(" ")
    if len(parts) < 2:
        return None
    for part in parts:
        if len(part) < 2 or _NAME_WORD.fullmatch(part) is None:
            return None
    return text
