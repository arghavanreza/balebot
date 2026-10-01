"""منطق گفتگوی بازو.

ورکر هر آپدیت بله را به handle_update می‌دهد. این فایل به محیط کلادفلر وصل نیست
تا بشود جریان‌ها را با حافظهٔ ساختگی و کلاینت ساختگی تست کرد.

کارهایی که این‌جا انجام می‌شود: منوی کاربر و مدیر، نمونهٔ اکسل، انتقال وجه تکی
با تایید روی دکمهٔ شیشه‌ای، دریافت لیست گروهی، اعتبارسنجی شبا، پرسش‌های متداول،
ویرایش متن، و فرستادن نتیجه فقط برای مدیر. ایمیل در این نسخه نیست.
ثبت کاربر در D1، خوش‌آمد با نام اگر پایگاه در دسترس باشد، گرفتن اجباری شمارهٔ
موبایل پیش از منوی خدمات برای مشتری، و آمار روزانهٔ /stats برای مدیر هم همین‌جاست.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from ccti import CctiConfigError, build_ccti, resolve_debtor
from excel_convert import ExcelConvertError, TransferBatch, parse_workbook
from faq import (
    MAX_ANSWER_LENGTH,
    MAX_FAQ_ITEMS,
    MAX_QUESTION_LENGTH,
    FaqFullError,
    FaqItem,
    FaqRepository,
    faq_keyboard,
    format_faq_answer,
    format_faq_menu,
    fresh_faq_id,
    match_faq_item,
    parse_faq_admin_input,
)
from phone import looks_like_phone_attempt, normalize_phone
from sample_loader import XLSX_MIME
from state import StateRepository, UpdateDedupe
from stats import STATS_DB_UNAVAILABLE, STATS_FAILED, format_stats, format_tehran_stamp, tehran_day_bounds
from texts import (
    DEFAULT_TEXTS,
    KEY_HELP,
    MAX_TEXT_LENGTH,
    TEXT_KEYS,
    TextRepository,
    render,
)
from transfer import (
    TransferRow,
    TransferValidationError,
    format_channel_companion,
    parse_destination,
    validate_beneficiary_name,
    validate_single,
)
from users import (
    RECENT_USER_LIMIT,
    USERS_DB_UNAVAILABLE,
    USERS_LIST_FAILED,
    UserProfile,
    UserStore,
    bale_user_from_update,
    format_recent_users,
    profile_from_bale_user,
    utc_now_iso,
)

# سقف دانلود فایل از بله، طبق مستند getFile. بزرگ‌تر از این را اصلاً نمی‌گیریم.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# ی و ک عربی را به فارسی برمی‌گردانیم و نیم‌فاصله را برمی‌داریم
# تا برچسب دکمه‌ای که با کیبورد عربی تایپ شده هم با متن ذخیره‌شده یکی شود.
_LETTER_FOLD = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": "", "\u200d": ""})


@dataclass
class BotContext:
    """همهٔ وابستگی‌های یک آپدیت. تست‌ها همین را با شیء ساختگی پر می‌کنند.

    users اختیاری است: اگر باندینگ DB نباشد بازو جواب می‌دهد ولی کسی ذخیره نمی‌شود.
    clock زمان ثبت بازدید است تا تست بتواند ساعت را ثابت نگه دارد.
    """

    texts: TextRepository
    states: StateRepository
    client: object
    admin_id: str
    load_sample: Callable[[], Awaitable[bytes]]
    converter: Callable[[bytes], TransferBatch | str] = parse_workbook
    dedupe: UpdateDedupe | None = None
    users: UserStore | None = None
    clock: Callable[[], str] = utc_now_iso
    # پرسش‌ها روی همان KV متن‌ها هستند، ولی سند جدا دارند. None یعنی این بخش خاموش است.
    faq: FaqRepository | None = None
    # خالی یعنی از متن debtor_* استفاده شود. ورود ورکر این‌ها را از DEBTOR_* پر می‌کند.
    # شبای مبدأ فقط باید معتبر و کد ۰۶۰ باشد؛ شعبهٔ خاصی این‌جا قید نمی‌شود.
    debtor_name: str = ""
    debtor_iban: str = ""
    debtor_bic: str = ""


def norm(text: str) -> str:
    """متن دکمه را برای مقایسه یکدست می‌کند: فاصلهٔ اضافه، ی/ک، و نیم‌فاصله."""
    return " ".join(text.translate(_LETTER_FOLD).split())


def command_name(text: str) -> str | None:
    """اگر پیام دستور اسلش باشد نامش را برمی‌گرداند. /start@MyBot هم /start است."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split()[0].split("@", 1)[0].lower()
    return head


def text_filename(original: str) -> str:
    """نام فایل متنی برای مدیر. فقط حرف انگلیسی می‌ماند چون هدر multipart باید ASCII باشد."""
    stem = Path(original or "sheet").stem
    cleaned = []
    for char in stem:
        if char.isascii() and (char.isalnum() or char in "-_"):
            cleaned.append(char)
        else:
            cleaned.append("_")
    base = "".join(cleaned).strip("_")[:40] or "sheet"
    return f"{base}.txt"


def clip(text: str, limit: int) -> str:
    """متن بلند را کوتاه می‌کند تا از سقف ارسال بله رد نشود."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def user_keyboard(texts: dict[str, str]) -> dict:
    """کیبورد مشتری: نمونه، انتقال تکی، انتقال گروهی، شبا و پرسش‌ها.

    هر برچسب یک ردیف است چون «ارسال لیست انتقال وجه» در ردیف مشترک جا نمی‌شود.
    خود آن دکمه داخل مرحلهٔ گروهی است؛ از منوی اصلی با «انتقال وجه گروهی» به آن می‌رسیم.
    """
    return {
        "keyboard": [
            [texts["btn_sample"]],
            [texts["btn_single"]],
            [texts["btn_group"]],
            [texts["btn_sheba"]],
            [texts["btn_faq"]],
        ]
    }


def admin_keyboard(texts: dict[str, str]) -> dict:
    """کیبورد مدیر. فهرست کاربران دکمه نیست؛ با دستور /users خوانده می‌شود."""
    return {
        "keyboard": [
            [texts["btn_edit"]],
            [texts["btn_faq_edit"]],
            [texts["btn_sample"]],
            [texts["btn_single"]],
            [texts["btn_group"]],
            [texts["btn_sheba"]],
            [texts["btn_faq"]],
        ]
    }


def phone_keyboard(texts: dict[str, str]) -> dict:
    """کیبورد اجباری شماره، تا وقتی موبایل مشتری در پرونده نباشد.

    request_contact فیلد رسمی دکمهٔ کیبورد بله است. با زدنش، خود بله شمارهٔ کاربر را
    به صورت پیام contact می‌فرستد و بازو لازم نیست شماره را از جای دیگری بخواند.
    دکمه‌های نمونه، انتقال، شبا و پرسش‌ها این‌جا نیستند و انصراف هم نیست:
    بدون شماره منوی خدمات باز نمی‌شود.
    """
    return {
        "keyboard": [
            [{"text": texts["btn_share_phone"], "request_contact": True}],
        ]
    }


def group_keyboard(texts: dict[str, str]) -> dict:
    """مرحلهٔ لیست گروهی. آپلود با فرستادن فایل است؛ دکمه فقط همان کار را یادآوری می‌کند."""
    return {
        "keyboard": [
            [texts["btn_group_send"]],
            [texts["btn_sample"]],
            [texts["btn_cancel"]],
        ]
    }


def confirm_inline_keyboard(texts: dict[str, str], token: str) -> dict:
    """دکمه‌های شیشه‌ای تایید و رد. توکن کوتاه است تا دکمهٔ قدیمی، انتقال تازه را ثبت نکند.

    callback_data باید ASCII و کوتاه باشد. بله همان شکل inline_keyboard تلگرام را می‌گیرد.
    """
    return {
        "inline_keyboard": [
            [
                {"text": texts["btn_transfer_ok"], "callback_data": f"xfer:ok:{token}"},
                {"text": texts["btn_transfer_no"], "callback_data": f"xfer:no:{token}"},
            ]
        ]
    }


def back_keyboard(texts: dict[str, str]) -> dict:
    """دکمهٔ بازگشت، وقتی مدیر دارد کلید متن را انتخاب می‌کند."""
    return {"keyboard": [[texts["btn_back"]]]}


def cancel_keyboard(texts: dict[str, str]) -> dict:
    """دکمهٔ انصراف، وسط وارد کردن شبا یا متن جدید."""
    return {"keyboard": [[texts["btn_cancel"]]]}


def menu_keyboard(texts: dict[str, str], is_admin: bool) -> dict:
    """کیبورد مناسب همان فرستنده. مدیر بودن فقط با برابری شناسه و ADMIN_ID است."""
    return admin_keyboard(texts) if is_admin else user_keyboard(texts)


def match_button(text: str, texts: dict[str, str]) -> str | None:
    """اگر متن دقیقاً برچسب یکی از دکمه‌ها باشد نام داخلی آن دکمه را برمی‌گرداند."""
    folded = norm(text)
    pairs = (
        ("sample", texts["btn_sample"]),
        ("single", texts["btn_single"]),
        ("group", texts["btn_group"]),
        ("group_send", texts["btn_group_send"]),
        ("sheba", texts["btn_sheba"]),
        ("faq", texts["btn_faq"]),
        ("faq_edit", texts["btn_faq_edit"]),
        ("faq_back", texts["btn_faq_back"]),
        ("edit", texts["btn_edit"]),
        ("back", texts["btn_back"]),
        ("cancel", texts["btn_cancel"]),
    )
    for name, label in pairs:
        if folded and folded == norm(label):
            return name
    return None


def resolve_text_key(text: str) -> str | None:
    """شمارهٔ ردیف منوی ویرایش، یا خود نام کلید، را به کلید متن تبدیل می‌کند."""
    raw = text.strip()
    if raw.isdigit():
        index = int(raw)
        if 1 <= index <= len(TEXT_KEYS):
            return TEXT_KEYS[index - 1]
        return None
    if raw in DEFAULT_TEXTS:
        return raw
    return None


def format_key_list(texts: dict[str, str]) -> str:
    """فهرستی که مدیر می‌بیند تا بداند کدام متن را عوض کند."""
    lines = [texts["admin_pick_prompt"], ""]
    for index, key in enumerate(TEXT_KEYS, start=1):
        lines.append(f"{index}. {key} — {KEY_HELP[key]}")
    return "\n".join(lines)


def _topic_label(action: str | None, texts: dict[str, str]) -> str | None:
    """کد آخرین کار را به برچسب مشتری تبدیل می‌کند. کد ناشناس یعنی موضوعی در کار نیست."""
    key = {
        "sample": "btn_sample",
        "sheba": "btn_sheba",
        "faq": "btn_faq",
        "excel": "topic_excel",
        "single": "btn_single",
    }.get(action or "")
    if not key:
        return None
    label = (texts.get(key) or "").strip()
    return label or None


def _greeting(texts: dict[str, str], profile: UserProfile) -> str:
    """خط اول /start.

    message_count بعد از ثبت همین پیام حساب می‌شود، پس ۱ یعنی اولین بازدید.
    موضوع فقط وقتی گفته می‌شود که واقعاً در پرونده ذخیره شده باشد.
    """
    name = profile.first_name
    if profile.message_count <= 1:
        if name:
            return render(texts["welcome_first"], name=name)
        return texts["welcome"]
    topic = _topic_label(profile.last_action, texts)
    if topic and name:
        return render(texts["welcome_back_topic"], name=name, topic=topic)
    if topic:
        return render(texts["welcome_back_topic_plain"], topic=topic)
    if name:
        return render(texts["welcome_back"], name=name)
    return texts["welcome_back_plain"]


def compose_customer_text(texts: dict[str, str], profile: UserProfile | None) -> str:
    """متن منوی مشتری.

    profile خالی یعنی خوش‌آمد عمومی: پایگاه نیست، خواندنش خطا داده، یا این پیام /start نبوده.
    جملهٔ فایل حقوق همیشه ته متن است تا پیش از آپلود دیده شود.
    """
    blocks = [texts["welcome"] if profile is None else _greeting(texts, profile)]
    for key in ("welcome_hint", "excel_upload_hint"):
        extra = (texts.get(key) or "").strip()
        if extra:
            blocks.append(extra)
    return "\n\n".join(part.strip() for part in blocks if part and part.strip())


def _is_xlsx(name: str, mime: str) -> bool:
    # پسوند را ملاک می‌گیریم و اگر نام خالی بود، نوع MIME استاندارد اکسل را.
    if name.lower().endswith(".xlsx"):
        return True
    return mime.lower() == XLSX_MIME


def _user_label(user: dict) -> str:
    """برچسب فرستنده در توضیح فایلی که برای مدیر می‌رود: @نام یا نام یا شناسه."""
    username = user.get("username")
    if isinstance(username, str) and username:
        return f"@{username}"
    parts = [user.get("first_name"), user.get("last_name")]
    name = " ".join(str(part) for part in parts if part)
    if name:
        return name
    return str(user.get("id") or "")


def _line_count(text: str) -> int:
    """تعداد سطر خروجی اکسل برای توضیح فایل مدیر. رشتهٔ خالی صفر سطر است."""
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _person_field(user: dict, profile: UserProfile | None, key: str) -> str:
    """نام را اول از همین پیام بله می‌گیرد و اگر نبود از پروندهٔ D1."""
    raw = user.get(key) if isinstance(user, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if profile is not None:
        stored = getattr(profile, key, None)
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
    return "—"


def _sender_fields(
    user: dict,
    user_id: str,
    seen_at: str,
    profile: UserProfile | None,
) -> dict[str, str]:
    """شناسه و نام و موبایل فرستنده برای پیام مدیر. شماره فقط از D1 می‌آید، نه از حدس."""
    username = user.get("username") if isinstance(user, dict) else None
    if not (isinstance(username, str) and username.strip()) and profile is not None:
        username = profile.username
    if isinstance(username, str) and username.strip():
        shown_username = "@" + username.strip().lstrip("@")
    else:
        shown_username = "ندارد"
    phone = profile.phone if profile is not None and profile.phone else "ثبت نشده"
    return {
        "user_label": _user_label(user),
        "user_id": user_id,
        "timestamp": format_tehran_stamp(seen_at),
        "first_name": _person_field(user, profile, "first_name"),
        "last_name": _person_field(user, profile, "last_name"),
        "username": shown_username,
        "phone": phone,
    }


def _excel_notice_fields(
    user: dict,
    user_id: str,
    filename: str,
    converted: str,
    seen_at: str,
    profile: UserProfile | None,
) -> dict[str, str]:
    """جای‌نگهدارهای خلاصه و توضیح فایل، به‌علاوهٔ مشخصات فرستنده."""
    fields = _sender_fields(user, user_id, seen_at, profile)
    fields.update(
        {
            "filename": filename or "upload.xlsx",
            "rows": str(_line_count(converted)),
            "chars": str(len(converted)),
        }
    )
    return fields


def _ids_match(user_id: object, admin_id: str) -> bool:
    """مدیر فقط کسی است که شناسه‌اش دقیقاً برابر ADMIN_ID باشد."""
    admin = (admin_id or "").strip()
    return bool(admin) and str(user_id) == admin


async def _remember_user(update: dict, ctx: BotContext) -> None:
    """فرستنده را در پایگاه کاربران ثبت می‌کند.

    خطا این‌جا خورده می‌شود تا قطع بودن D1 یا نبودن جدول، جواب بازو را نشکند.
    شمارش بعد از dedupe است؛ پس تکرار همان آپدیت (تلاش دوبارهٔ بله) یک بار دیگر جمع نمی‌شود.
    """
    if ctx.users is None:
        return
    raw_user = bale_user_from_update(update)
    if raw_user is None:
        return
    profile = profile_from_bale_user(
        raw_user,
        is_admin=_ids_match(raw_user.get("id"), ctx.admin_id),
        seen_at=ctx.clock(),
    )
    if profile is None:
        return
    try:
        await ctx.users.touch(profile)
    except Exception as exc:
        print("user upsert failed:", type(exc).__name__)


async def _load_profile(ctx: BotContext, user_id: str) -> UserProfile | None:
    """پروندهٔ همین کاربر را برای خوش‌آمد می‌خواند.

    نبودن متد get (پایگاه قدیمی یا ساختگی ناقص) و هر خطای خواندن، None برمی‌گرداند
    تا /start با متن عمومی ادامه پیدا کند.
    """
    if ctx.users is None:
        return None
    getter = getattr(ctx.users, "get", None)
    if not callable(getter):
        return None
    try:
        numeric = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        profile = await getter(numeric)
    except Exception as exc:
        print("user get failed:", type(exc).__name__)
        return None
    if not isinstance(profile, UserProfile):
        return None
    return profile


async def _record_event(
    ctx: BotContext,
    user_id: str,
    kind: str,
    detail: str | None = None,
) -> None:
    """یک رویداد آمار می‌نویسد. نبودن جدول یا پایگاه، جواب بازو را نمی‌شکند."""
    if ctx.users is None:
        return
    recorder = getattr(ctx.users, "record_event", None)
    if not callable(recorder):
        return
    try:
        numeric = int(user_id)
    except (TypeError, ValueError):
        return
    try:
        await recorder(numeric, kind, ctx.clock(), detail)
    except Exception as exc:
        print("event record failed:", type(exc).__name__)


async def _phone_required(ctx: BotContext, user_id: str, is_admin: bool) -> bool:
    """مشتری بدون شمارهٔ ذخیره‌شده باید اول موبایل بدهد.

    مدیر از این در رد می‌شود تا پنل بدون شماره هم باز بماند.
    اگر پایگاه نباشد یا set_phone نداشته باشیم، در را نمی‌بندیم: شماره جایی
    برای ماندن ندارد و قطع بودن D1 نباید کل بازو را قفل کند.
    خطای خواندن پرونده هم None است و در را نمی‌بندد، همان‌طور که خوش‌آمد عمومی می‌ماند.
    شمارهٔ ذخیره‌شده فقط وقتی کافی است که نرمال‌سازی موبایل ایران را رد کند.
    """
    if is_admin or ctx.users is None:
        return False
    if not callable(getattr(ctx.users, "set_phone", None)):
        return False
    profile = await _load_profile(ctx, user_id)
    if profile is None:
        return False
    return normalize_phone(profile.phone) is None


async def _require_phone(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
    *,
    greet: bool,
) -> None:
    """مشتری را پشت در شماره نگه می‌دارد و کیبورد خدمات را نشان نمی‌دهد.

    greet فقط برای /start است: اول همان خوش‌آمد، بعد توضیح شماره.
    بقیهٔ پیام‌ها یک یادآوری کوتاه می‌گیرند تا هر بار متن بلند تکرار نشود.
    """
    await ctx.states.set(user_id, {"flow": "phone"})
    if greet:
        profile = await _load_profile(ctx, user_id)
        greeting = texts["welcome"] if profile is None else _greeting(texts, profile)
        # راهنمای دکمه‌های خدمات این‌جا نیست؛ آن دکمه‌ها هنوز نشان داده نمی‌شوند.
        await reply(greeting, phone_keyboard(texts))
        await reply(texts["phone_prompt"], phone_keyboard(texts))
        return
    reminder = texts.get("phone_required") or texts["phone_prompt"]
    await reply(reminder, phone_keyboard(texts))


async def _save_phone(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
    is_admin: bool,
    raw_phone: str,
) -> None:
    """شمارهٔ معتبر را در D1 می‌نویسد و جریان را می‌بندد. last_action این‌جا عوض نمی‌شود."""
    canonical = normalize_phone(raw_phone)
    markup = menu_keyboard(texts, is_admin)
    if canonical is None:
        await reply(texts["phone_invalid"], phone_keyboard(texts) if not is_admin else markup)
        return
    if ctx.users is None or not callable(getattr(ctx.users, "set_phone", None)):
        await ctx.states.clear(user_id)
        await reply(texts["phone_store_failed"], markup)
        return
    try:
        await ctx.users.set_phone(int(user_id), canonical)  # type: ignore[attr-defined]
    except Exception as exc:
        print("phone save failed:", type(exc).__name__)
        await reply(texts["phone_store_failed"], phone_keyboard(texts) if not is_admin else markup)
        return
    await ctx.states.clear(user_id)
    body = render(texts["phone_saved"], phone=canonical)
    if not is_admin:
        # بعد از ثبت، راهنمای منو را همان‌جا می‌گذاریم تا دکمه‌های تازه‌ظاهرشده بی‌توضیح نمانند.
        extras = [
            (texts.get(key) or "").strip()
            for key in ("welcome_hint", "excel_upload_hint")
        ]
        hint = "\n\n".join(part for part in extras if part)
        if hint:
            body = body + "\n\n" + hint
    await reply(body, markup)


def _contact_phone(contact: dict) -> str | None:
    """شماره را از شیء contact بله برمی‌دارد. عدد و رشته هر دو پذیرفته می‌شوند."""
    number = contact.get("phone_number")
    if isinstance(number, bool) or number is None:
        return None
    if isinstance(number, int):
        return str(number)
    if isinstance(number, str) and number.strip():
        return number
    return None


def _contact_is_own(contact: dict, user_id: str) -> bool:
    """اگر بله user_id مخاطب را داده باشد باید با فرستنده یکی باشد.

    نبودن این فیلد را رد نمی‌کنیم: بعضی کلاینت‌ها فقط phone_number می‌فرستند.
    ناهماهنگی یعنی کاربر مخاطب شخص دیگری را فرستاده و نباید در پرونده‌اش بنشیند.
    """
    owner = contact.get("user_id")
    if owner is None:
        return True
    if isinstance(owner, bool):
        return False
    return str(owner) == str(user_id)


async def _note_action(ctx: BotContext, user_id: str, action: str) -> None:
    """آخرین کار را ذخیره می‌کند. خطا این‌جا خورده می‌شود تا گفتگو نشکند."""
    if ctx.users is None:
        return
    setter = getattr(ctx.users, "set_last_action", None)
    if not callable(setter):
        return
    try:
        numeric = int(user_id)
    except (TypeError, ValueError):
        return
    try:
        await setter(numeric, action)
    except Exception as exc:
        print("last action failed:", type(exc).__name__)


async def handle_update(update: dict, ctx: BotContext) -> None:
    """یک آپدیت بله را پردازش می‌کند: یا callback، یا پیام.

    وب‌هوک و cron هر دو از همین تابع می‌آیند. اول تکراری بودن را کنار می‌گذاریم،
    بعد کاربر را ثبت می‌کنیم، بعد جواب می‌دهیم.
    """
    if not isinstance(update, dict):
        return
    if ctx.dedupe is not None and not await ctx.dedupe.claim(update.get("update_id")):
        return

    await _remember_user(update, ctx)

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        await _handle_callback(callback, ctx)
        return

    message = update.get("message")
    if isinstance(message, dict):
        await _handle_message(message, ctx)


def _parse_transfer_callback(data: object) -> tuple[str, str] | None:
    """دادهٔ دکمهٔ شیشه‌ای تایید/رد را به (ok|no, token) تبدیل می‌کند. شکل دیگر یعنی دکمهٔ این جریان نیست."""
    if not isinstance(data, str):
        return None
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "xfer" or parts[1] not in {"ok", "no"}:
        return None
    token = parts[2].strip()
    if not token:
        return None
    return parts[1], token


def _transfer_decision_word(text: str, texts: dict[str, str]) -> str | None:
    """اگر مشتری به‌جای دکمه، تایید یا رد را تایپ کرده باشد همان تصمیم را برمی‌گرداند.

    همزهٔ روی الف را برمی‌داریم تا «تأیید» و «تایید» یکی شوند. این تا کردن سراسری نیست
    تا برچسب دکمه‌های دیگر ناخواسته عوض نشود.
    """
    folded = norm(text).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ئ", "ی")
    if folded == norm(texts["btn_transfer_ok"]).replace("أ", "ا") or folded == "تایید":
        return "ok"
    if folded == norm(texts["btn_transfer_no"]) or folded == "رد":
        return "no"
    return None


async def _handle_callback(callback: dict, ctx: BotContext) -> None:
    """کلیک دکمهٔ شیشه‌ای را جواب می‌دهد تا نشان «در حال بارگذاری» روی بله بماند.

    تایید و رد انتقال تکی همین‌جا تمام می‌شود. هر callback دیگر فقط بسته می‌شود.
    """
    callback_id = callback.get("id")
    if callback_id is None:
        return
    parsed = _parse_transfer_callback(callback.get("data"))
    if parsed is None:
        await ctx.client.answer_callback_query(str(callback_id))  # type: ignore[attr-defined]
        return
    decision, token = parsed
    await _handle_transfer_callback(callback, ctx, str(callback_id), decision, token)


async def _handle_message(message: dict, ctx: BotContext) -> None:
    """یک پیام را به دستور، دکمه، جریان باز (شبا یا ویرایش)، یا فایل اکسل وصل می‌کند."""
    user = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    # اگر from نباشد (نادر)، شناسهٔ گفتگو را برای جواب دادن به کار می‌بریم.
    # ذخیرهٔ کاربر جداست و فقط from معتبر را می‌نویسد.
    user_id = str(user.get("id") or chat.get("id") or "")
    chat_id = chat.get("id", user.get("id"))
    if not user_id or chat_id is None:
        return

    is_admin = _ids_match(user_id, ctx.admin_id)
    texts = await ctx.texts.snapshot()

    async def reply(text: str, reply_markup: dict | None = None) -> None:
        # پیام خالی را نمی‌فرستیم؛ بله آن را رد می‌کند و گفتگو گیر می‌کند.
        body = (text or "").strip()
        if not body:
            return
        await ctx.client.send_message(chat_id, body, reply_markup=reply_markup)  # type: ignore[attr-defined]

    async def show_menu(personal: bool = False) -> None:
        # خوش‌آمد مدیر و کاربر جداست تا مشتری دکمهٔ ویرایش متن را نبیند.
        # personal فقط برای /start است تا «خوش برگشتی» وسط انصراف تکرار نشود.
        if is_admin:
            await reply(texts["admin_intro"], admin_keyboard(texts))
            return
        profile = await _load_profile(ctx, user_id) if personal else None
        await reply(compose_customer_text(texts, profile), user_keyboard(texts))

    # مشتریِ بدون شماره از همین‌جا رد نمی‌شود. مدیر و پایگاهِ قطع این پرچم را False می‌گیرند.
    needs_phone = await _phone_required(ctx, user_id, is_admin)

    # فایل را قبل از متن بررسی می‌کنیم. ارسال اکسل هر جریان نیمه‌کاره (شبا یا ویرایش) را می‌بندد.
    # بدون شماره، فایل پردازش نمی‌شود تا واریز حقوق پیش از ثبت موبایل به مدیر نرسد.
    document = message.get("document")
    if isinstance(document, dict) and document.get("file_id"):
        if needs_phone:
            await _require_phone(ctx, texts, reply, user_id, greet=False)
            return
        await ctx.states.clear(user_id)
        await _handle_document(
            document,
            ctx,
            texts,
            reply,
            is_admin=is_admin,
            user=user,
            user_id=user_id,
        )
        return

    # پیام contact متن ندارد. قبل از رد کردن پیام بی‌متن، شماره را برمی‌داریم.
    # مخاطب حتی بیرون از جریان phone پذیرفته می‌شود تا دکمهٔ request_contact در را باز کند.
    contact = message.get("contact")
    if isinstance(contact, dict):
        await _handle_contact(contact, ctx, texts, reply, user_id, is_admin)
        return

    raw_text = message.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return

    command = command_name(raw_text)
    if command == "/start":
        await ctx.states.clear(user_id)
        print(f"start user_id={user_id} admin={is_admin}")
        if needs_phone:
            await _require_phone(ctx, texts, reply, user_id, greet=True)
            return
        await show_menu(personal=True)
        return
    if needs_phone:
        # /id خدمات شعبه نیست؛ شناسه را می‌گوییم ولی کیبورد همان درخواست شماره می‌ماند.
        if command == "/id":
            print(f"id user_id={user_id}")
            await ctx.states.set(user_id, {"flow": "phone"})
            await reply(render(texts["id_reply"], user_id=user_id), phone_keyboard(texts))
            return
        # شمارهٔ ناقص یا ثابت هم باید «نشناختم» بگیرد، نه یادآوری عمومی.
        # دکمهٔ نمونه و «سلام» رقم موبایل نیستند؛ یادآوری می‌گیرند و منو باز نمی‌شود.
        if looks_like_phone_attempt(raw_text):
            await ctx.states.set(user_id, {"flow": "phone"})
            await _save_phone(ctx, texts, reply, user_id, is_admin, raw_text)
            return
        await _require_phone(ctx, texts, reply, user_id, greet=False)
        return
    if command == "/cancel":
        await ctx.states.clear(user_id)
        await reply(texts["cancelled"], menu_keyboard(texts, is_admin))
        return
    if command == "/id":
        # شناسه را در لاگ هم می‌نویسیم تا بشود ADMIN_ID را از tail پیدا کرد.
        print(f"id user_id={user_id}")
        await reply(render(texts["id_reply"], user_id=user_id), menu_keyboard(texts, is_admin))
        return
    if command == "/users":
        # فهرست کاربران دستور است نه دکمه، تا کیبورد مشتری شلوغ نشود.
        if not is_admin:
            await reply(texts["not_admin"], menu_keyboard(texts, is_admin))
            return
        await _send_user_list(ctx, reply, menu_keyboard(texts, is_admin))
        return
    if command == "/stats":
        # مثل /users دستور است نه دکمه، و فقط ADMIN_ID آن را می‌بیند.
        if not is_admin:
            await reply(texts["not_admin"], menu_keyboard(texts, is_admin))
            return
        await _send_stats(ctx, reply, menu_keyboard(texts, is_admin))
        return
    if command:
        await reply(texts["unknown_text"], menu_keyboard(texts, is_admin))
        return

    state = await ctx.states.get(user_id)
    flow = state.get("flow")

    # دستورهای اسلش بالاتر جواب داده شده‌اند و به این‌جا نمی‌رسند.
    # هنگام گرفتن متن جدید، فقط برچسب انصراف جریان را قطع می‌کند.
    # هر متن دیگر، حتی اگر شبیه دکمهٔ دیگر باشد، همان مقدار تازه است.
    # اگر بخواهند خود برچسب انصراف را ذخیره کنند، اول باید برچسب انصراف را عوض کنند.
    if flow == "edit_value":
        if not is_admin:
            await ctx.states.clear(user_id)
            await reply(texts["not_admin"], user_keyboard(texts))
            return
        if match_button(raw_text, texts) == "cancel":
            await ctx.states.clear(user_id)
            await reply(texts["cancelled"], menu_keyboard(texts, is_admin))
            return
        await _save_text(raw_text, state, ctx, texts, reply, is_admin, user_id)
        return

    # متن پرسش و پاسخ ممکن است شبیه برچسب دکمه باشد. این دو جریان را قبل از دکمه‌ها می‌گیریم
    # و فقط انصراف قطعشان می‌کند، مثل ویرایش متن.
    if flow in {"faq_edit_q", "faq_edit_a"}:
        if not is_admin:
            await ctx.states.clear(user_id)
            await reply(texts["not_admin"], user_keyboard(texts))
            return
        if match_button(raw_text, texts) == "cancel":
            await ctx.states.clear(user_id)
            await reply(texts["cancelled"], menu_keyboard(texts, is_admin))
            return
        if flow == "faq_edit_q":
            await _save_faq_question(raw_text, state, ctx, texts, reply, user_id)
            return
        await _save_faq_answer(raw_text, state, ctx, texts, reply, is_admin, user_id)
        return

    action = match_button(raw_text, texts)
    if action in {"back", "cancel"}:
        await ctx.states.clear(user_id)
        if action == "cancel":
            await reply(texts["cancelled"])
        await show_menu()
        return
    if action == "sample":
        await ctx.states.clear(user_id)
        await _note_action(ctx, user_id, "sample")
        await _send_sample(ctx, texts, reply, chat_id, is_admin, user_id)
        return
    if action == "single":
        await ctx.states.set(user_id, {"flow": "transfer_name"})
        await _note_action(ctx, user_id, "single")
        await reply(texts["transfer_ask_name"], cancel_keyboard(texts))
        return
    if action in {"group", "group_send"}:
        await ctx.states.set(user_id, {"flow": "group"})
        await _note_action(ctx, user_id, "excel")
        prompt = texts["group_prompt"] if action == "group" else texts["group_need_file"]
        await reply(prompt, group_keyboard(texts))
        return
    if action == "sheba":
        await ctx.states.set(user_id, {"flow": "sheba"})
        await _note_action(ctx, user_id, "sheba")
        await _record_event(ctx, user_id, "sheba")
        await reply(texts["sheba_prompt"], cancel_keyboard(texts))
        return
    if action in {"faq", "faq_back"}:
        await _note_action(ctx, user_id, "faq")
        await _show_faq_list(ctx, texts, reply, user_id)
        return
    if action == "faq_edit":
        if not is_admin:
            await reply(texts["not_admin"], user_keyboard(texts))
            return
        await _show_faq_admin(ctx, texts, reply, user_id)
        return
    if action == "edit":
        if not is_admin:
            await reply(texts["not_admin"], user_keyboard(texts))
            return
        await ctx.states.set(user_id, {"flow": "edit_pick"})
        await reply(format_key_list(texts), back_keyboard(texts))
        return

    if flow == "edit_pick":
        if not is_admin:
            await ctx.states.clear(user_id)
            await reply(texts["not_admin"], user_keyboard(texts))
            return
        key = resolve_text_key(raw_text)
        if key is None:
            await reply(texts["admin_bad_key"], back_keyboard(texts))
            return
        await ctx.states.set(user_id, {"flow": "edit_value", "key": key})
        await reply(
            render(
                texts["admin_value_prompt"],
                key=key,
                current=clip(texts.get(key, ""), 800),
            ),
            cancel_keyboard(texts),
        )
        return

    if flow == "sheba":
        await _handle_sheba(raw_text, ctx, texts, reply, user_id, is_admin)
        return

    if flow == "transfer_name":
        await _transfer_got_name(raw_text, ctx, texts, reply, user_id)
        return
    if flow == "transfer_account":
        await _transfer_got_account(raw_text, state, ctx, texts, reply, user_id)
        return
    if flow == "transfer_amount":
        await _transfer_got_amount(raw_text, state, ctx, texts, reply, user_id)
        return
    if flow == "transfer_confirm":
        decision = _transfer_decision_word(raw_text, texts)
        if decision is None:
            await reply(texts["transfer_need_choice"])
            return
        await _apply_transfer_decision(
            ctx,
            texts,
            reply,
            user_id=user_id,
            is_admin=is_admin,
            user=user,
            decision=decision,
            token=str(state.get("token") or ""),
            callback_id=None,
        )
        return
    if flow == "group":
        await reply(texts["group_need_file"], group_keyboard(texts))
        return

    if flow == "faq_admin":
        if not is_admin:
            await ctx.states.clear(user_id)
            await reply(texts["not_admin"], user_keyboard(texts))
            return
        await _handle_faq_admin_text(raw_text, ctx, texts, reply, user_id)
        return

    if flow == "faq":
        await _handle_faq_choice(raw_text, ctx, texts, reply, user_id)
        return

    # دکمهٔ پرسش ممکن است از کیبورد قبلی مانده باشد. شمارهٔ تنها این‌جا بازش نمی‌کند.
    if await _open_faq_label(raw_text, ctx, texts, reply, user_id):
        return

    # جریان phone اگر هنوز مانده باشد مال نسخه‌ای است که شماره اختیاری بود،
    # یا ذخیره تمام شده و وضعیت پاک نشده. این‌جا دیگر متن عادی را شماره حساب نمی‌کنیم.
    if flow == "phone":
        await ctx.states.clear(user_id)

    # نه دستور بود، نه دکمه، نه فایل. راهنمای کوتاه می‌فرستیم و منو را دوباره نشان می‌دهیم.
    await reply(texts["unknown_text"], menu_keyboard(texts, is_admin))


async def _send_user_list(
    ctx: BotContext,
    reply: Callable[..., Awaitable[None]],
    markup: dict,
) -> None:
    """جواب /users. نبودن پایگاه یا خطای خواندن، گفتگو را خراب نمی‌کند."""
    if ctx.users is None:
        await reply(USERS_DB_UNAVAILABLE, markup)
        return
    try:
        rows = await ctx.users.list_recent(RECENT_USER_LIMIT)
    except Exception as exc:
        print("user list failed:", type(exc).__name__)
        await reply(USERS_LIST_FAILED, markup)
        return
    await reply(clip(format_recent_users(rows), 3500), markup)


async def _send_stats(
    ctx: BotContext,
    reply: Callable[..., Awaitable[None]],
    markup: dict,
) -> None:
    """جواب /stats. نبودن پایگاه یا خطای خواندن، گفتگو را خراب نمی‌کند.

    امروز یعنی نیمه‌شب تا نیمه‌شب بعد به وقت تهران. تعریف دقیق داخل متن جواب است.
    """
    if ctx.users is None or not callable(getattr(ctx.users, "stats_between", None)):
        await reply(STATS_DB_UNAVAILABLE, markup)
        return
    try:
        start, end, day_label = tehran_day_bounds(ctx.clock())
        snapshot = await ctx.users.stats_between(start, end)  # type: ignore[attr-defined]
    except Exception as exc:
        print("stats failed:", type(exc).__name__)
        await reply(STATS_FAILED, markup)
        return
    await reply(clip(format_stats(snapshot, day_label=day_label), 3500), markup)


async def _handle_contact(
    contact: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
    is_admin: bool,
) -> None:
    """پیام contact بله را به شمارهٔ پرونده تبدیل می‌کند."""
    if not _contact_is_own(contact, user_id):
        markup = phone_keyboard(texts) if not is_admin else menu_keyboard(texts, True)
        await reply(texts["phone_not_own"], markup)
        return
    raw_phone = _contact_phone(contact)
    if raw_phone is None:
        markup = phone_keyboard(texts) if not is_admin else menu_keyboard(texts, True)
        await reply(texts["phone_invalid"], markup)
        return
    await _save_phone(ctx, texts, reply, user_id, is_admin, raw_phone)


async def _save_text(
    raw_text: str,
    state: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    is_admin: bool,
    user_id: str,
) -> None:
    """متن تازه را در KV می‌نویسد و جریان ویرایش را می‌بندد. کلید ناشناس ذخیره نمی‌شود."""
    key = state.get("key")
    if not isinstance(key, str) or key not in DEFAULT_TEXTS:
        await ctx.states.clear(user_id)
        await reply(texts["admin_bad_key"], menu_keyboard(texts, is_admin))
        return
    value = raw_text.strip()
    if not value:
        await reply(texts["admin_empty"], cancel_keyboard(texts))
        return
    if len(value) > MAX_TEXT_LENGTH:
        await reply(texts["admin_too_long"], cancel_keyboard(texts))
        return
    await ctx.texts.update(key, value)
    await ctx.states.clear(user_id)
    fresh = await ctx.texts.snapshot()
    await reply(render(fresh["admin_saved"], key=key), menu_keyboard(fresh, is_admin))


async def _handle_sheba(
    raw_text: str,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
    is_admin: bool,
) -> None:
    # فقط همین شاخه به قواعد شبا نیاز دارد، برای همین واردات کنار خود بررسی است.
    from sheba import validate_sheba

    result = validate_sheba(raw_text)
    if result.valid:
        await ctx.states.clear(user_id)
        await reply(
            render(texts["sheba_valid"], sheba=result.normalized),
            menu_keyboard(texts, is_admin),
        )
        return
    shown = result.normalized or clip(raw_text.strip().replace("\n", " "), 80)
    # در حالت شبا می‌مانیم تا پیام بعدی تلاش تازه باشد، نه یک متن ناشناس.
    await reply(render(texts["sheba_invalid"], sheba=shown), cancel_keyboard(texts))


async def _send_sample(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    chat_id: object,
    is_admin: bool,
    user_id: str,
) -> None:
    """فایل نمونه را برای خود همان چت می‌فرستد، نه برای مدیر."""
    try:
        data = await ctx.load_sample()
    except Exception as exc:
        print("sample load failed:", type(exc).__name__)
        await reply(texts["sample_missing"], menu_keyboard(texts, is_admin))
        return
    if not data:
        await reply(texts["sample_missing"], menu_keyboard(texts, is_admin))
        return
    await ctx.client.send_document(  # type: ignore[attr-defined]
        chat_id,
        "sample.xlsx",
        data,
        caption=texts["sample_caption"],
        mime=XLSX_MIME,
        reply_markup=menu_keyboard(texts, is_admin),
    )
    # فقط ارسال موفق شمرده می‌شود. فایل گم‌شده رویداد sample نمی‌سازد.
    await _record_event(ctx, user_id, "sample")


def _as_batch(value: object) -> TransferBatch:
    """مبدل قدیمی فقط متن برمی‌گرداند. آن را بسته‌ای بدون سطر حساب می‌کنیم تا همچنان فایل متنی برود."""
    if isinstance(value, TransferBatch):
        return value
    if isinstance(value, str):
        return TransferBatch(rows=[], text=value, truncated=False)
    raise ExcelConvertError("converter returned nothing usable")


def _nonce(user_id: str) -> int:
    digits = "".join(char for char in user_id if char.isdigit())
    if not digits:
        return 0
    return int(digits) % 1000


def ccti_filename(original: str) -> str:
    """نام ASCII برای فایل پایا. هدر multipart بله نام فارسی را خراب می‌کند."""
    stem = text_filename(original)
    if stem.endswith(".txt"):
        stem = stem[: -len(".txt")]
    if not stem or stem == "sheet":
        return "paya.ccti"
    return f"{stem}.ccti"


def _count_channels(rows: list[TransferRow]) -> dict[str, str]:
    paya = [row for row in rows if row.channel == "paya"]
    return {
        "rows": str(len(rows)),
        "internal": str(sum(row.channel == "internal" for row in rows)),
        "paya": str(len(paya)),
        "satna": str(sum(row.channel == "satna" for row in rows)),
        "paya_sum": str(sum(row.amount for row in paya)),
        "paya_file": "دارد" if paya else "ندارد",
    }


async def _deliver_transfers(
    ctx: BotContext,
    texts: dict[str, str],
    *,
    admin_id: str,
    user: dict,
    user_id: str,
    profile: UserProfile | None,
    rows: list[TransferRow],
    companion: str | None,
    source_name: str,
    summary_key: str,
    extra_fields: dict[str, str] | None = None,
) -> bool:
    """خلاصه و در صورت نیاز ccti و متن همراه را برای مدیر می‌فرستد.

    False یعنی فایلی که باید می‌رفت نرسید. خطای تنظیم مبدأ، پیش از هر ارسالی، بالا می‌رود
    تا نیمهٔ فایل برای مدیر نرود و ارسال دوباره سطر تکراری نسازد.
    شکست خود پیام خلاصه مانع فایل نمی‌شود.
    """
    paya = [row for row in rows if row.channel == "paya"]
    xml: str | None = None
    if paya:
        debtor = resolve_debtor(
            texts,
            name=ctx.debtor_name,
            iban=ctx.debtor_iban,
            bic=ctx.debtor_bic,
        )
        xml = build_ccti(paya, debtor, now_iso=ctx.clock(), nonce=_nonce(user_id))
    if xml is None and not (companion and companion.strip()):
        return False

    seen_at = ctx.clock()
    fields = _sender_fields(user, user_id, seen_at, profile)
    fields.update(_count_channels(rows))
    fields.update(
        {
            "filename": ccti_filename(source_name) if xml else text_filename(source_name),
            "chars": str(len(companion or xml or "")),
            "user_label": _user_label(user),
        }
    )
    if extra_fields:
        fields.update(extra_fields)
    summary = render(texts.get(summary_key, ""), **fields).strip()
    if summary:
        try:
            # خلاصه کیبورد نمی‌فرستد تا منوی مدیر، اگر وسط ویرایش باشد، جابه‌جا نشود.
            await ctx.client.send_message(admin_id, clip(summary, 3500))  # type: ignore[attr-defined]
        except Exception as exc:
            print("transfer summary failed:", type(exc).__name__)

    caption = render(texts["excel_admin_caption"], **fields)
    last_markup = admin_keyboard(texts)
    try:
        if xml is not None:
            await ctx.client.send_document(  # type: ignore[attr-defined]
                admin_id,
                ccti_filename(source_name),
                xml.encode("utf-8"),
                caption=caption,
                mime="application/xml",
                reply_markup=None if companion else last_markup,
            )
        if companion and companion.strip():
            await ctx.client.send_document(  # type: ignore[attr-defined]
                admin_id,
                text_filename(source_name),
                companion.encode("utf-8"),
                caption=caption,
                mime="text/plain; charset=utf-8",
                reply_markup=last_markup,
            )
    except Exception as exc:
        print("transfer deliver failed:", type(exc).__name__)
        return False
    return True


async def _handle_document(
    document: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    *,
    is_admin: bool,
    user: dict,
    user_id: str,
) -> None:
    """اکسل را می‌سنجد و نتیجه را فقط برای ADMIN_ID می‌فرستد.

    سطر پایا فایل ccti است. داخلی و ساتنا، و شرح پایا، متن می‌مانند.
    پیش از فایل یک خلاصه می‌رود. اگر خود خلاصه ارسال نشود، فایل همچنان فرستاده می‌شود.
    فایل نامعتبر برای مدیر نمی‌رود.
    """
    name = str(document.get("file_name") or "")
    mime = str(document.get("mime_type") or "")
    markup = menu_keyboard(texts, is_admin)
    if not _is_xlsx(name, mime):
        await reply(texts["excel_bad_type"], markup)
        return
    # نوع فایل درست است؛ حتی اگر دانلود بعداً بشکند، آخرین کار «ارسال فایل حقوق» مانده است.
    await _note_action(ctx, user_id, "excel")
    size = document.get("file_size")
    if isinstance(size, (int, float)) and not isinstance(size, bool) and size > MAX_DOWNLOAD_BYTES:
        await reply(texts["excel_too_large"], markup)
        return

    file_id = str(document.get("file_id"))
    try:
        data = await ctx.client.get_file_bytes(file_id)  # type: ignore[attr-defined]
    except Exception as exc:
        print("excel download failed:", type(exc).__name__)
        await reply(texts["excel_download_failed"], markup)
        return

    try:
        batch = _as_batch(ctx.converter(data))
    except TransferValidationError as exc:
        # فایل خوانا بوده ولی سطرها رد شده‌اند. مدیر چیزی نمی‌گیرد.
        await reply(clip(exc.user_message, 3500), markup)
        return
    except ExcelConvertError:
        await reply(texts["excel_parse_error"], markup)
        return
    except Exception as exc:
        print("excel convert failed:", type(exc).__name__)
        await reply(texts["excel_parse_error"], markup)
        return

    admin_id = (ctx.admin_id or "").strip()
    if not admin_id:
        await reply(texts["excel_no_admin"], markup)
        return

    profile = await _load_profile(ctx, user_id)
    try:
        delivered = await _deliver_transfers(
            ctx,
            texts,
            admin_id=admin_id,
            user=user,
            user_id=user_id,
            profile=profile,
            rows=batch.rows,
            companion=format_channel_companion(batch.rows, truncated=batch.truncated)
            if batch.rows
            else (batch.text or None),
            source_name=name or "upload.xlsx",
            summary_key="excel_admin_summary",
        )
    except CctiConfigError as exc:
        await reply(exc.user_message, markup)
        return
    if not delivered:
        await reply(texts["excel_deliver_failed"], markup)
        return

    # رویداد را بعد از رسیدن فایل می‌نویسیم تا ارسال ناموفق در آمار امروز نیاید.
    await _record_event(ctx, user_id, "excel")
    await reply(texts["excel_ack"], markup)


async def _faq_items(ctx: BotContext) -> list[FaqItem]:
    """فهرست پرسش‌ها. خطای KV به فهرست خالی تبدیل می‌شود تا گفتگو قطع نشود."""
    if ctx.faq is None:
        return []
    try:
        return await ctx.faq.list_items()
    except Exception as exc:
        print("faq load failed:", type(exc).__name__)
        return []


def _faq_markup(texts: dict[str, str], items: list[FaqItem]) -> dict:
    if not items:
        return back_keyboard(texts)
    return faq_keyboard(items, texts["btn_faq_back"], texts["btn_back"])


async def _show_faq_list(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    """فهرست پرسش‌ها را نشان می‌دهد و جریان را روی faq می‌گذارد تا شماره هم جواب بدهد."""
    items = await _faq_items(ctx)
    await ctx.states.set(user_id, {"flow": "faq"})
    if not items:
        await reply(texts["faq_empty"], back_keyboard(texts))
        return
    await reply(format_faq_menu(texts["faq_intro"], items), _faq_markup(texts, items))


async def _handle_faq_choice(
    raw_text: str,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    items = await _faq_items(ctx)
    found = match_faq_item(raw_text, items, allow_number=True)
    if found is None:
        await reply(texts["faq_bad_choice"], _faq_markup(texts, items))
        return
    await _note_action(ctx, user_id, "faq")
    # هر باز شدن پاسخ یک رویداد faq است. detail متن پرسش است تا /stats پرتکرار را بگوید.
    await _record_event(ctx, user_id, "faq", found.question)
    await reply(format_faq_answer(found), _faq_markup(texts, items))


async def _open_faq_label(
    raw_text: str,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> bool:
    """اگر متن دقیقاً برچسب یک پرسش باشد پاسخ را باز می‌کند. شمارهٔ تنها را نادیده می‌گیرد."""
    items = await _faq_items(ctx)
    found = match_faq_item(raw_text, items, allow_number=False)
    if found is None:
        return False
    await ctx.states.set(user_id, {"flow": "faq"})
    await _note_action(ctx, user_id, "faq")
    await _record_event(ctx, user_id, "faq", found.question)
    await reply(format_faq_answer(found), _faq_markup(texts, items))
    return True


async def _show_faq_admin(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
    prefix: str = "",
) -> None:
    """منوی ویرایش پرسش برای مدیر. prefix تأیید ذخیره یا حذف است که بالای فهرست می‌آید."""
    await ctx.states.set(user_id, {"flow": "faq_admin"})
    items = await _faq_items(ctx)
    if items:
        body = format_faq_menu(texts["faq_admin_prompt"], items)
    else:
        body = texts["faq_admin_prompt"].strip() + "\n\n" + texts["faq_empty"].strip()
    lead = prefix.strip()
    if lead:
        body = lead + "\n\n" + body
    await reply(body, back_keyboard(texts))


def _faq_admin_bad(texts: dict[str, str]) -> str:
    return render(texts["faq_admin_bad"], add=texts["faq_cmd_add"], delete=texts["faq_cmd_delete"])


async def _handle_faq_admin_text(
    raw_text: str,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    items = await _faq_items(ctx)
    parsed = parse_faq_admin_input(
        raw_text,
        add_word=texts["faq_cmd_add"],
        delete_word=texts["faq_cmd_delete"],
        count=len(items),
    )
    if parsed is None or parsed[0] == "invalid":
        await reply(_faq_admin_bad(texts), back_keyboard(texts))
        return
    kind, number = parsed
    if kind == "delete" and number is not None:
        if ctx.faq is None:
            await reply(texts["faq_empty"], back_keyboard(texts))
            return
        removed = await ctx.faq.delete(items[number - 1].id)
        if not removed:
            await reply(_faq_admin_bad(texts), back_keyboard(texts))
            return
        await _show_faq_admin(ctx, texts, reply, user_id, prefix=texts["faq_deleted"])
        return
    if kind == "add":
        if len(items) >= MAX_FAQ_ITEMS:
            await reply(render(texts["faq_full"], max=MAX_FAQ_ITEMS), back_keyboard(texts))
            return
        await ctx.states.set(user_id, {"flow": "faq_edit_q"})
        await reply(render(texts["faq_ask_question"], current="—"), cancel_keyboard(texts))
        return
    if kind == "edit" and number is not None:
        item = items[number - 1]
        await ctx.states.set(user_id, {"flow": "faq_edit_q", "id": item.id})
        await reply(
            render(texts["faq_ask_question"], current=clip(item.question, 800)),
            cancel_keyboard(texts),
        )


async def _save_faq_question(
    raw_text: str,
    state: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    """پرسش تازه را در وضعیت نگه می‌دارد و پاسخ را می‌پرسد. هنوز در KV نوشته نمی‌شود."""
    question = raw_text.strip()
    if not question:
        await reply(texts["admin_empty"], cancel_keyboard(texts))
        return
    if len(question) > MAX_QUESTION_LENGTH:
        await reply(texts["admin_too_long"], cancel_keyboard(texts))
        return
    item_id = state.get("id")
    current_answer = "—"
    if isinstance(item_id, str):
        for item in await _faq_items(ctx):
            if item.id == item_id:
                current_answer = clip(item.answer, 800)
                break
    next_state: dict = {"flow": "faq_edit_a", "question": question}
    if isinstance(item_id, str) and item_id:
        next_state["id"] = item_id
    await ctx.states.set(user_id, next_state)
    await reply(render(texts["faq_ask_answer"], current=current_answer), cancel_keyboard(texts))


async def _save_faq_answer(
    raw_text: str,
    state: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    is_admin: bool,
    user_id: str,
) -> None:
    """پرسش و پاسخ را با هم در KV می‌نویسد. شناسهٔ تازه فقط برای پرسش جدید ساخته می‌شود."""
    answer = raw_text.strip()
    if not answer:
        await reply(texts["admin_empty"], cancel_keyboard(texts))
        return
    if len(answer) > MAX_ANSWER_LENGTH:
        await reply(texts["admin_too_long"], cancel_keyboard(texts))
        return
    question = state.get("question")
    if not isinstance(question, str) or not question.strip() or ctx.faq is None:
        await ctx.states.clear(user_id)
        await reply(_faq_admin_bad(texts), menu_keyboard(texts, is_admin))
        return
    item_id = state.get("id")
    if not isinstance(item_id, str) or not item_id:
        item_id = fresh_faq_id(await _faq_items(ctx))
    try:
        await ctx.faq.upsert(FaqItem(id=item_id, question=question.strip(), answer=answer))
    except FaqFullError:
        await ctx.states.clear(user_id)
        await reply(render(texts["faq_full"], max=MAX_FAQ_ITEMS), menu_keyboard(texts, is_admin))
        return
    await _show_faq_admin(ctx, texts, reply, user_id, prefix=texts["faq_saved"])


async def _transfer_got_name(
    raw_text: str,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    """نام را نگه می‌دارد و سراغ شبا یا حساب می‌رود. خطا جریان را روی همین مرحله می‌گذارد."""
    error = validate_beneficiary_name(raw_text)
    if error:
        await reply(error, cancel_keyboard(texts))
        return
    await ctx.states.set(user_id, {"flow": "transfer_account", "name": " ".join(raw_text.split())})
    await reply(texts["transfer_ask_account"], cancel_keyboard(texts))


async def _transfer_got_account(
    raw_text: str,
    state: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    destination, error = parse_destination(raw_text)
    if error or destination is None:
        await reply(error or texts["transfer_ask_account"], cancel_keyboard(texts))
        return
    name = state.get("name")
    if not isinstance(name, str) or not name.strip():
        await ctx.states.set(user_id, {"flow": "transfer_name"})
        await reply(texts["transfer_ask_name"], cancel_keyboard(texts))
        return
    await ctx.states.set(
        user_id,
        {"flow": "transfer_amount", "name": name.strip(), "account": destination.normalized},
    )
    await reply(texts["transfer_ask_amount"], cancel_keyboard(texts))


async def _transfer_got_amount(
    raw_text: str,
    state: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    user_id: str,
) -> None:
    """مبلغ را با همان قواعد اکسل می‌سنجد و خلاصه را با دکمهٔ شیشه‌ای نشان می‌دهد."""
    name = state.get("name")
    account = state.get("account")
    if not isinstance(name, str) or not isinstance(account, str):
        await ctx.states.clear(user_id)
        await reply(texts["transfer_stale"], cancel_keyboard(texts))
        return
    row, error = validate_single(name, account, raw_text)
    if error or row is None:
        await reply(error or texts["transfer_ask_amount"], cancel_keyboard(texts))
        return
    token = secrets.token_hex(4)
    await ctx.states.set(
        user_id,
        {
            "flow": "transfer_confirm",
            "name": row.name,
            "account": row.account,
            "amount": str(row.amount),
            "token": token,
        },
    )
    summary = render(
        texts["transfer_confirm"],
        beneficiary=row.name,
        account=row.account,
        amount=str(row.amount),
        channel=row.channel_label,
    )
    await reply(summary, confirm_inline_keyboard(texts, token))


async def _handle_transfer_callback(
    callback: dict,
    ctx: BotContext,
    callback_id: str,
    decision: str,
    token: str,
) -> None:
    """کلیک تایید یا رد را به همان تصمیمی می‌رساند که تایپ کردن آن کلمه‌ها می‌رسد."""
    user = callback.get("from") if isinstance(callback.get("from"), dict) else {}
    message = callback.get("message") if isinstance(callback.get("message"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    user_id = str(user.get("id") or chat.get("id") or "")
    chat_id = chat.get("id", user.get("id"))
    answered = False

    async def toast(text: str | None = None) -> None:
        nonlocal answered
        if answered:
            return
        answered = True
        await ctx.client.answer_callback_query(callback_id, text)  # type: ignore[attr-defined]

    if not user_id or chat_id is None:
        await toast()
        return

    texts = await ctx.texts.snapshot()
    is_admin = _ids_match(user_id, ctx.admin_id)

    async def reply(text: str, reply_markup: dict | None = None) -> None:
        body = (text or "").strip()
        if not body:
            return
        await ctx.client.send_message(chat_id, body, reply_markup=reply_markup)  # type: ignore[attr-defined]

    try:
        await _apply_transfer_decision(
            ctx,
            texts,
            reply,
            user_id=user_id,
            is_admin=is_admin,
            user=user,
            decision=decision,
            token=token,
            callback_id=callback_id,
            toast=toast,
        )
    finally:
        await toast()


async def _apply_transfer_decision(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    *,
    user_id: str,
    is_admin: bool,
    user: dict,
    decision: str,
    token: str,
    callback_id: str | None,
    toast: Callable[..., Awaitable[None]] | None = None,
) -> None:
    """تایید را برای مدیر می‌فرستد و رد را بدون خبر به مدیر می‌بندد.

    توکن باید با وضعیت فعلی یکی باشد. دکمهٔ پیام قبلی، بعد از شروع انتقال تازه، اثر ندارد.
    وضعیت را پیش از ارسال برمی‌داریم تا دو کلیک پشت‌سرهم دو بار به مدیر نرسد.
    اگر ارسال بشکند، همان وضعیت را برمی‌گردانیم تا مشتری دوباره تایید کند.
    """

    async def say(text: str | None = None) -> None:
        if toast is not None:
            await toast(text)

    state = await ctx.states.get(user_id)
    stored_token = str(state.get("token") or "")
    # توکن خالی یعنی این وضعیت مال تایید نیست، حتی اگر جریان درست مانده باشد.
    if state.get("flow") != "transfer_confirm" or not stored_token or stored_token != token:
        await say(texts["transfer_stale"])
        await reply(texts["transfer_stale"], menu_keyboard(texts, is_admin))
        return

    if decision == "no":
        await ctx.states.clear(user_id)
        await say(texts["transfer_cancelled"])
        await reply(texts["transfer_cancelled"], menu_keyboard(texts, is_admin))
        return

    name = state.get("name")
    account = state.get("account")
    amount = state.get("amount")
    if not isinstance(name, str) or not isinstance(account, str) or not isinstance(amount, str):
        await ctx.states.clear(user_id)
        await say(texts["transfer_stale"])
        await reply(texts["transfer_stale"], menu_keyboard(texts, is_admin))
        return

    row, error = validate_single(name, account, amount)
    if error or row is None:
        await ctx.states.clear(user_id)
        await say(texts["transfer_stale"])
        await reply(error or texts["transfer_stale"], menu_keyboard(texts, is_admin))
        return

    admin_id = (ctx.admin_id or "").strip()
    if not admin_id:
        await ctx.states.clear(user_id)
        await say(texts["excel_no_admin"])
        await reply(texts["excel_no_admin"], menu_keyboard(texts, is_admin))
        return

    profile = await _load_profile(ctx, user_id)
    if row.channel == "paya":
        # ساخت فایل پیش از پاک کردن وضعیت است تا شبای مبدأ خراب، تایید را نسوزاند.
        try:
            delivered = await _deliver_transfers(
                ctx,
                texts,
                admin_id=admin_id,
                user=user,
                user_id=user_id,
                profile=profile,
                rows=[row],
                companion=format_channel_companion([row], truncated=False),
                source_name="paya.xlsx",
                summary_key="transfer_admin",
                extra_fields={
                    "beneficiary": row.name,
                    "account": row.account,
                    "amount": str(row.amount),
                    "channel": row.channel_label,
                    "attachment": "فایل پایا (ccti) پیوست است.",
                },
            )
        except CctiConfigError as exc:
            await say(exc.user_message)
            await reply(exc.user_message, menu_keyboard(texts, is_admin))
            return
        if not delivered:
            await say(texts["excel_deliver_failed"])
            await reply(texts["excel_deliver_failed"], menu_keyboard(texts, is_admin))
            return
        await ctx.states.clear(user_id)
        await say(texts["transfer_ack"])
        await reply(texts["transfer_ack"], menu_keyboard(texts, is_admin))
        return

    await ctx.states.clear(user_id)
    fields = _sender_fields(user, user_id, ctx.clock(), profile)
    fields.update(
        {
            "beneficiary": row.name,
            "account": row.account,
            "amount": str(row.amount),
            "channel": row.channel_label,
            "attachment": "",
        }
    )
    notice = render(texts["transfer_admin"], **fields).strip()
    try:
        await ctx.client.send_message(admin_id, clip(notice, 3500))  # type: ignore[attr-defined]
    except Exception as exc:
        print("transfer deliver failed:", type(exc).__name__)
        await ctx.states.set(user_id, state)
        await say(texts["excel_deliver_failed"])
        await reply(texts["excel_deliver_failed"], menu_keyboard(texts, is_admin))
        return

    await say(texts["transfer_ack"])
    await reply(texts["transfer_ack"], menu_keyboard(texts, is_admin))
