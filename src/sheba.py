"""بررسی شماره شبا (IBAN ایرانی).

قاعدهٔ عمومی IBAN این است: چهار نویسهٔ اول را به ته ببر، حرف‌ها را به عدد تبدیل کن
(A برابر ۱۰ تا Z برابر ۳۵) و باقی‌ماندهٔ تقسیم بر ۹۷ باید ۱ باشد.
شبا ایران یعنی IR به‌علاوهٔ ۲۴ رقم، روی هم ۲۶ نویسه.
این ماژول فقط محاسبه است و به بله یا ورکر وصل نیست تا بشود بدون شبکه تستش کرد.
"""

from __future__ import annotations

from dataclasses import dataclass

# رقم فارسی و عربی را به انگلیسی برمی‌گردانیم تا بقیهٔ حساب فقط رقم ASCII ببیند.
_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


@dataclass(frozen=True)
class ShebaCheck:
    """نتیجهٔ بررسی.

    normalized وقتی شکل IR و ۲۴ رقم درست باشد پر است، حتی اگر رقم کنترلی غلط باشد،
    تا به کاربر همان عدد تمیزشده را نشان بدهیم. اگر اصلاً شکل شبا نباشد خالی است.
    reason یکی از ok، format یا checksum است و فقط برای لاگ و تست است، نه متن مشتری.
    """

    valid: bool
    normalized: str
    reason: str


def _expand_alnum(value: str) -> str | None:
    """حرف‌های IBAN را به عدد تبدیل می‌کند. نویسهٔ غیرمجاز یعنی کل شماره رد است."""
    parts: list[str] = []
    for char in value:
        if char.isdigit():
            parts.append(char)
        elif "A" <= char <= "Z":
            parts.append(str(ord(char) - 55))
        else:
            return None
    return "".join(parts)


def _mod97(number: str) -> int:
    # باقی‌مانده را رقم‌به‌رقم حساب می‌کنیم تا کل عدد را یک‌جا نسازیم.
    # نتیجه با «خود عدد به‌پیمانهٔ ۹۷» یکی است.
    remainder = 0
    for char in number:
        remainder = (remainder * 10 + int(char)) % 97
    return remainder


def iban_is_valid(iban: str) -> bool:
    """رقم کنترلی IBAN را چک می‌کند. فاصله باید از قبل حذف شده باشد.

    این تابع کشور را محدود نمی‌کند. اجبار شکل IR و ۲۴ رقم کار validate_sheba است.
    """
    compact = iban.upper()
    if len(compact) < 5 or not compact.isalnum() or not compact[:2].isalpha():
        return False
    rearranged = compact[4:] + compact[:4]
    expanded = _expand_alnum(rearranged)
    if expanded is None:
        return False
    return _mod97(expanded) == 1


def iban_check_digits(country: str, bban: str) -> str:
    """دو رقم کنترلی را برای ساختن نمونهٔ معتبر حساب می‌کند. ورودی نباید فاصله داشته باشد."""
    country = country.upper()
    if len(country) != 2 or not country.isalpha():
        raise ValueError("country must be two letters")
    if not bban.isalnum():
        raise ValueError("bban must be alphanumeric")
    rearranged = f"{bban}{country}00"
    expanded = _expand_alnum(rearranged)
    if expanded is None:
        raise ValueError("bban must be alphanumeric")
    return f"{98 - _mod97(expanded):02d}"


def normalize_sheba(raw: str) -> str | None:
    """متن کاربر را به IR و ۲۴ رقم تبدیل می‌کند. اگر شکلش این نباشد None برمی‌گردد.

    فاصله، خط تیره و کلمهٔ «شبا» نادیده گرفته می‌شوند. رقم فارسی و عربی قبول است.
    بدون پیشوند IR نامعتبر است تا شمارهٔ خام بانک با شبا قاطی نشود.
    """
    if not isinstance(raw, str):
        return None
    text = raw.translate(_DIGIT_TRANSLATION).upper()
    text = text.replace("شبا", "").replace("IBAN", "")
    compact = "".join(char for char in text if char.isalnum())
    if len(compact) != 26 or not compact.startswith("IR"):
        return None
    digits = compact[2:]
    if len(digits) != 24 or not digits.isdigit():
        return None
    return compact


def validate_sheba(raw: str) -> ShebaCheck:
    """شبا را هم از نظر شکل و هم از نظر رقم کنترلی می‌سنجد. این همان تابعی است که بازو صدا می‌زند."""
    normalized = normalize_sheba(raw)
    if normalized is None:
        return ShebaCheck(valid=False, normalized="", reason="format")
    if not iban_is_valid(normalized):
        return ShebaCheck(valid=False, normalized=normalized, reason="checksum")
    return ShebaCheck(valid=True, normalized=normalized, reason="ok")


# کد بانک قرض‌الحسنه مهر ایران داخل شبا. جایگاهش رقم‌های ۵ تا ۷ است
# (بعد از IR و دو رقم کنترل). شعبهٔ داخل شماره این‌جا مهم نیست.
MEHR_BANK_CODE = "060"


def sheba_bank_code(raw: str) -> str | None:
    """کد سه رقمی بانک را از شبا برمی‌گرداند. شکل غلط یعنی None، حتی اگر رقم کنترل غلط باشد."""
    normalized = normalize_sheba(raw)
    if normalized is None:
        return None
    return normalized[4:7]


def is_mehr_sheba(raw: str) -> bool:
    """شبای معتبر بانک مهر است یا نه. شعبه هر چه باشد، فقط کد ۰۶۰ ملاک است."""
    check = validate_sheba(raw)
    if not check.valid:
        return False
    return check.normalized[4:7] == MEHR_BANK_CODE
