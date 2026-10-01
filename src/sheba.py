"""Iranian IBAN (Sheba / شبا) checks.

The public rule is ISO 13616 with the ISO 7064 MOD 97-10 checksum:
move the first four characters to the end, expand letters (A=10 … Z=35),
and require the integer value modulo 97 to equal 1.

An Iranian Sheba is the country code IR plus 24 digits (26 characters).
"""

from __future__ import annotations

from dataclasses import dataclass

# Persian (۰-۹) and Arabic-Indic (٠-٩) digits → ASCII.
_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


@dataclass(frozen=True)
class ShebaCheck:
    """Result of a Sheba check.

    `normalized` is `IR` + 24 digits when the shape is acceptable, even if the
    checksum fails. It is empty when the text is not an IR Sheba at all.
    `reason` is `ok`, `format`, or `checksum`.
    """

    valid: bool
    normalized: str
    reason: str


def _expand_alnum(value: str) -> str | None:
    """Expand an IBAN rearrangement to digits. None if a character is illegal."""
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
    remainder = 0
    for char in number:
        remainder = (remainder * 10 + int(char)) % 97
    return remainder


def iban_is_valid(iban: str) -> bool:
    """Return True when `iban` passes ISO 7064 MOD 97-10.

    Spaces must already be removed. Country is not restricted here;
    `validate_sheba` is what enforces the IR + 24 digits shape.
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
    """Return the two check digits for a country code and BBAN (no spaces)."""
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
    """Return `IR` + 24 digits, or None when the text is not that shape.

    Spaces, dashes, and the Persian word «شبا» are ignored. Persian and
    Arabic-Indic digits are accepted. The IR prefix is required.
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
    """Validate a customer-supplied Iranian Sheba number."""
    normalized = normalize_sheba(raw)
    if normalized is None:
        return ShebaCheck(valid=False, normalized="", reason="format")
    if not iban_is_valid(normalized):
        return ShebaCheck(valid=False, normalized=normalized, reason="checksum")
    return ShebaCheck(valid=True, normalized=normalized, reason="ok")
