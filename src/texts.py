"""متن‌هایی که مشتری و مدیر می‌بینند.

پیش‌فرض‌ها همین‌جا هستند. بار اول که ورکر آن‌ها را بخواند در KV با کلید bot_texts
ذخیره می‌شوند و بعد از منوی مدیر عوض می‌شوند، بدون استقرار مجدد.
اگر مدیر یک کلید را ذخیره کرده باشد، عوض کردن پیش‌فرض در کد آن مقدار را بازنویسی نمی‌کند.
کلید تازه‌ای که در نسخهٔ بعدی کد اضافه شود با پیش‌فرض پر می‌شود و بقیهٔ ویرایش‌ها می‌مانند.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

# Maximum stored message. Bale sendMessage allows 4096 characters.
MAX_TEXT_LENGTH = 3500

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

# هر ردیف: کلید، متن پیش‌فرض فارسی، توضیح کوتاه برای خود منوی ویرایش.
# توضیح سوم برای مشتری فرستاده نمی‌شود؛ فقط به مدیر می‌گوید این کلید چیست.
_SPEC: tuple[tuple[str, str, str], ...] = (
    (
        "welcome",
        "سلام، به بازوی تبدیل اکسل خوش آمدید.\n"
        "فایل اکسل (.xlsx) را همین‌جا بفرستید تا به متن تبدیل شود و برای مدیر ارسال گردد.",
        "پیام خوش‌آمد کاربر",
    ),
    (
        "welcome_hint",
        "از دکمه‌های پایین می‌توانید نمونهٔ فایل را بگیرید یا شماره شبا را بررسی کنید.",
        "راهنمای کوتاه زیر خوش‌آمد",
    ),
    (
        "admin_intro",
        "پنل مدیر فعال است.\n"
        "با «ویرایش متن» پیام‌ها و برچسب دکمه‌ها را عوض کنید.\n"
        "برای دیدن کاربران اخیر دستور /users را بفرستید.\n"
        "ارسال فایل .xlsx برای شما هم مثل کاربران پردازش می‌شود و نتیجه به همین شناسهٔ مدیر می‌رسد.",
        "پیام شروع مخصوص مدیر",
    ),
    ("btn_sample", "دریافت سمپل اکسل", "برچسب دکمهٔ دریافت نمونه اکسل"),
    ("btn_sheba", "بررسی شبا", "برچسب دکمهٔ بررسی شبا"),
    ("btn_edit", "ویرایش متن", "برچسب دکمهٔ ویرایش متن"),
    ("btn_back", "بازگشت", "برچسب دکمهٔ بازگشت"),
    ("btn_cancel", "انصراف", "برچسب دکمهٔ انصراف"),
    (
        "sample_caption",
        "نمونهٔ فایل اکسل. ستون‌های فعلی: name، amount، sheba. مقادیر فقط جای‌نگهدارند.",
        "توضیح همراه فایل نمونه",
    ),
    (
        "sample_missing",
        "فایل نمونه روی سرور پیدا نشد. لطفاً کمی بعد دوباره تلاش کنید.",
        "خطا: فایل نمونه موجود نیست",
    ),
    (
        "sheba_prompt",
        "شماره شبا را بفرستید.\nشکل درست: IR و سپس ۲۴ رقم. فاصله و ارقام فارسی پذیرفته می‌شود.",
        "درخواست شماره شبا",
    ),
    (
        "sheba_valid",
        "شماره شبا معتبر است.\n{sheba}",
        "پاسخ شبا معتبر. جای‌نگهدار: {sheba}",
    ),
    (
        "sheba_invalid",
        "شماره شبا نامعتبر است.\n"
        "باید با IR شروع شود، ۲۴ رقم داشته باشد و رقم کنترلی (ISO 7064) درست باشد.\n"
        "مقدار دریافتی: {sheba}",
        "پاسخ شبا نامعتبر. جای‌نگهدار: {sheba}",
    ),
    (
        "excel_ack",
        "فایل شما دریافت شد و پس از تبدیل برای مدیر ارسال گردید.",
        "تأیید دریافت اکسل برای فرستنده",
    ),
    (
        "excel_admin_caption",
        "فایل تبدیل‌شده\n"
        "کاربر: {user_label}\n"
        "شناسه: {user_id}\n"
        "نام فایل: {filename}\n"
        "تعداد سطر: {rows}",
        "توضیح فایل متنی برای مدیر. جای‌نگهدارها: {user_label} {user_id} {filename} {rows}",
    ),
    (
        "excel_bad_type",
        "فقط فایل اکسل با پسوند .xlsx پذیرفته می‌شود.",
        "خطا: نوع فایل غیر از xlsx",
    ),
    (
        "excel_parse_error",
        "خواندن این فایل اکسل ممکن نشد. لطفاً فایل را بررسی و دوباره ارسال کنید.",
        "خطا: فایل اکسل ناخوانا",
    ),
    (
        "excel_download_failed",
        "دانلود فایل از بله ناموفق بود. لطفاً دوباره ارسال کنید.",
        "خطا: دانلود فایل از بله",
    ),
    (
        "excel_too_large",
        "حجم فایل بیش از حد مجاز دانلود (۲۰ مگابایت) است.",
        "خطا: فایل بزرگ‌تر از سقف دانلود",
    ),
    (
        "excel_no_admin",
        "شناسهٔ مدیر در تنظیمات بازو ثبت نشده و فایل تحویل داده نشد.",
        "خطا: ADMIN_ID خالی است",
    ),
    (
        "excel_deliver_failed",
        "فایل دریافت شد ولی ارسال آن برای مدیر ناموفق بود. لطفاً کمی بعد دوباره تلاش کنید.",
        "خطا: ارسال فایل متنی به مدیر",
    ),
    (
        "unknown_text",
        "این پیام را متوجه نشدم. فایل .xlsx بفرستید یا یکی از دکمه‌ها را بزنید.",
        "پاسخ به متن ناشناخته",
    ),
    (
        "id_reply",
        "شناسهٔ عددی شما: {user_id}\nاین عدد را به‌عنوان ADMIN_ID در تنظیمات ورکر قرار دهید.",
        "پاسخ دستور /id. جای‌نگهدار: {user_id}",
    ),
    (
        "admin_pick_prompt",
        "شماره یا نام کلید را بفرستید:",
        "راهنمای انتخاب کلید متن",
    ),
    (
        "admin_value_prompt",
        "متن جدید برای «{key}» را در یک پیام بفرستید.\nمتن فعلی:\n{current}",
        "درخواست متن جدید. جای‌نگهدارها: {key} {current}",
    ),
    ("admin_saved", "متن «{key}» ذخیره شد.", "تأیید ذخیره. جای‌نگهدار: {key}"),
    (
        "admin_bad_key",
        "این کلید شناخته نشد. شماره یا نام کلید را از فهرست بفرستید.",
        "کلید نامعتبر در ویرایش متن",
    ),
    ("admin_empty", "متن خالی ذخیره نمی‌شود.", "رد شدن متن خالی"),
    (
        "admin_too_long",
        "متن طولانی‌تر از حد مجاز است. متن کوتاه‌تری بفرستید.",
        "رد شدن متن خیلی بلند",
    ),
    ("cancelled", "عملیات لغو شد.", "پیام لغو جریان"),
    ("not_admin", "این بخش فقط برای مدیر بازو است.", "دسترسی غیرمجاز به پنل مدیر"),
)

DEFAULT_TEXTS: dict[str, str] = {key: value for key, value, _help in _SPEC}
KEY_HELP: dict[str, str] = {key: help_text for key, _value, help_text in _SPEC}
TEXT_KEYS: tuple[str, ...] = tuple(key for key, _value, _help in _SPEC)

_KV_KEY = "bot_texts"


class KeyValue(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def put(self, key: str, value: str, ttl: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...


def render(template: str, **kwargs: object) -> str:
    """جای‌نگهدارهای {name} را پر می‌کند. نام ناشناس و آکولاد تکی دست‌نخورده می‌مانند تا متن مدیر خراب نشود."""

    values = {key: "" if value is None else str(value) for key, value in kwargs.items()}

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return values[key]
        return match.group(0)

    return _PLACEHOLDER.sub(replace, "" if template is None else str(template))


class TextRepository:
    """نسخهٔ KV از متن‌های پیش‌فرض. کلید غایب از همین پیش‌فرض‌ها پر می‌شود."""

    def __init__(self, kv: KeyValue) -> None:
        self.kv = kv

    async def snapshot(self) -> dict[str, str]:
        """متن مؤثر هر کلید را برمی‌گرداند: پیش‌فرض، و روی آن هر چیزی که مدیر ذخیره کرده."""
        raw = await self.kv.get(_KV_KEY)
        stored: dict | None = None
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                stored = parsed

        merged = dict(DEFAULT_TEXTS)
        if stored:
            for key, value in stored.items():
                if key in DEFAULT_TEXTS and isinstance(value, str):
                    merged[key] = value

        # بار اول کل سند را می‌نویسیم. اگر کد کلید تازه آورده باشد فقط همان‌ها به سند قبلی اضافه می‌شوند.
        if stored is None or any(key not in stored for key in DEFAULT_TEXTS):
            await self.kv.put(_KV_KEY, json.dumps(merged, ensure_ascii=False))
        return merged

    async def update(self, key: str, value: str) -> None:
        """یک کلید شناخته‌شده را عوض می‌کند. کلید خارج از فهرست عمداً خطا است تا سند KV کثیف نشود."""
        if key not in DEFAULT_TEXTS:
            raise KeyError(key)
        current = await self.snapshot()
        current[key] = value
        await self.kv.put(_KV_KEY, json.dumps(current, ensure_ascii=False))
