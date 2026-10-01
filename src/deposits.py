"""کیبورد شیشه‌ای سپرده‌ها.

دکمهٔ پایین چت فقط در «سپرده‌های من» را باز می‌کند.
خود فهرست، افزودن و حذف دکمه‌های inline هستند که بله آن‌ها را شیشه‌ای نشان می‌دهد
و callback_query می‌فرستد. دادهٔ callback کوتاه است چون سقفش کوچک است؛ شبا داخل دکمهٔ متن است
و شناسهٔ عددی سپرده داخل callback می‌رود.
"""

from __future__ import annotations

from sheba import is_mehr_sheba, validate_sheba

MAX_DEPOSITS = 15
_LABEL_LIMIT = 40


def parse_deposit_callback(data: object) -> tuple[str, int | None] | None:
    """dep:add و dep:del و dep:back و dep:use:۱۲ و dep:rm:۱۲ را می‌خواند."""
    if not isinstance(data, str):
        return None
    parts = data.strip().split(":")
    if len(parts) < 2 or parts[0] != "dep":
        return None
    action = parts[1]
    if action in {"add", "del", "back"} and len(parts) == 2:
        return action, None
    if action in {"use", "rm"} and len(parts) == 3 and parts[2].isdigit():
        number = int(parts[2])
        if number > 0:
            return action, number
    return None


def deposits_keyboard(deposits: list, *, add_label: str, delete_label: str) -> dict:
    """هر سپرده یک دکمه است. سپردهٔ مبدأ با تیک مشخص می‌شود. افزودن و حذف ردیف آخرند."""
    rows: list[list[dict[str, str]]] = []
    for deposit in deposits:
        mark = "مبدأ " if deposit.is_active else ""
        label = f" ({deposit.label})" if getattr(deposit, "label", None) else ""
        text = f"{mark}{deposit.sheba}{label}"
        if len(text) > 60:
            text = text[:59] + "…"
        rows.append([{"text": text, "callback_data": f"dep:use:{deposit.id}"}])
    rows.append(
        [
            {"text": add_label, "callback_data": "dep:add"},
            {"text": delete_label, "callback_data": "dep:del"},
        ]
    )
    return {"inline_keyboard": rows}


def delete_keyboard(deposits: list, *, back_label: str) -> dict:
    rows = []
    for deposit in deposits:
        text = f"حذف {deposit.sheba}"
        if len(text) > 60:
            text = text[:59] + "…"
        rows.append([{"text": text, "callback_data": f"dep:rm:{deposit.id}"}])
    rows.append([{"text": back_label, "callback_data": "dep:back"}])
    return {"inline_keyboard": rows}


def split_sheba_and_label(raw: str) -> tuple[str, str | None] | None:
    """شبا را از متن جدا می‌کند. اگر خط دوم باشد برچسب است.

    فاصله داخل خود شبا پذیرفته می‌شود، برای همین اول کل خط اول را می‌سنجیم
    و فقط وقتی شبا نبود سراغ تکه‌ها می‌رویم.
    """
    if not isinstance(raw, str):
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return None
    first = validate_sheba(lines[0])
    if first.valid:
        label = " ".join(lines[1:]).strip()
        return first.normalized, _clean_label(label)
    for token in lines[0].split():
        checked = validate_sheba(token)
        if checked.valid:
            rest = lines[0].replace(token, "", 1).strip()
            extra = " ".join(lines[1:]).strip()
            label = " ".join(part for part in (rest, extra) if part)
            return checked.normalized, _clean_label(label)
    return None


def mehr_sheba_or_none(raw: str) -> str | None:
    """شبا را برمی‌گرداند فقط اگر مهر باشد. برای دکمهٔ اعتبارسنجی عمومی این تابع را صدا نزنید."""
    found = split_sheba_and_label(raw)
    if found is None:
        return None
    sheba, _label = found
    if not is_mehr_sheba(sheba):
        return None
    return sheba


def _clean_label(label: str) -> str | None:
    cleaned = " ".join(label.split())
    if not cleaned:
        return None
    return cleaned[:_LABEL_LIMIT]
