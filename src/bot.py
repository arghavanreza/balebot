"""منطق گفتگوی بازو.

ورکر هر آپدیت بله را به handle_update می‌دهد. این فایل به محیط کلادفلر وصل نیست
تا بشود جریان‌ها را با حافظهٔ ساختگی و کلاینت ساختگی تست کرد.

کارهایی که این‌جا انجام می‌شود: منوی کاربر و مدیر، نمونهٔ اکسل، بررسی شبا،
ویرایش متن، تبدیل فایل اکسل و فرستادن نتیجه فقط برای مدیر، و ثبت کاربر در D1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from excel_convert import ExcelConvertError, convert_excel_to_text
from sample_loader import XLSX_MIME
from state import StateRepository, UpdateDedupe
from texts import (
    DEFAULT_TEXTS,
    KEY_HELP,
    MAX_TEXT_LENGTH,
    TEXT_KEYS,
    TextRepository,
    render,
)
from users import (
    RECENT_USER_LIMIT,
    USERS_DB_UNAVAILABLE,
    USERS_LIST_FAILED,
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
    converter: Callable[[bytes], str] = convert_excel_to_text
    dedupe: UpdateDedupe | None = None
    users: UserStore | None = None
    clock: Callable[[], str] = utc_now_iso


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
    """کیبورد پایین چت برای کاربر عادی: نمونهٔ اکسل و بررسی شبا."""
    return {"keyboard": [[texts["btn_sample"]], [texts["btn_sheba"]]]}


def admin_keyboard(texts: dict[str, str]) -> dict:
    """کیبورد مدیر. فهرست کاربران دکمه نیست؛ با دستور /users خوانده می‌شود."""
    return {
        "keyboard": [
            [texts["btn_edit"]],
            [texts["btn_sample"], texts["btn_sheba"]],
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
        ("sheba", texts["btn_sheba"]),
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


async def _handle_callback(callback: dict, ctx: BotContext) -> None:
    """کلیک دکمهٔ شیشه‌ای را جواب می‌دهد تا نشان «در حال بارگذاری» روی بله بماند.

    خود ثبت کاربر قبل از این تابع انجام شده است. این بازو فعلاً منوی شیشه‌ای ندارد
    و فقط callback را می‌بندد.
    """
    callback_id = callback.get("id")
    if callback_id is None:
        return
    await ctx.client.answer_callback_query(str(callback_id))  # type: ignore[attr-defined]


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

    async def show_menu() -> None:
        # خوش‌آمد مدیر و کاربر جداست تا مشتری دکمهٔ ویرایش متن را نبیند.
        if is_admin:
            await reply(texts["admin_intro"], admin_keyboard(texts))
            return
        parts = [texts["welcome"].strip()]
        hint = texts["welcome_hint"].strip()
        if hint:
            parts.append(hint)
        await reply("\n\n".join(part for part in parts if part), user_keyboard(texts))

    # فایل را قبل از متن بررسی می‌کنیم. ارسال اکسل هر جریان نیمه‌کاره (شبا یا ویرایش) را می‌بندد.
    document = message.get("document")
    if isinstance(document, dict) and document.get("file_id"):
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

    raw_text = message.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return

    command = command_name(raw_text)
    if command == "/start":
        await ctx.states.clear(user_id)
        print(f"start user_id={user_id} admin={is_admin}")
        await show_menu()
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

    action = match_button(raw_text, texts)
    if action in {"back", "cancel"}:
        await ctx.states.clear(user_id)
        if action == "cancel":
            await reply(texts["cancelled"])
        await show_menu()
        return
    if action == "sample":
        await ctx.states.clear(user_id)
        await _send_sample(ctx, texts, reply, chat_id, is_admin)
        return
    if action == "sheba":
        await ctx.states.set(user_id, {"flow": "sheba"})
        await reply(texts["sheba_prompt"], cancel_keyboard(texts))
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
    """اکسل را به متن تبدیل می‌کند و فایل متنی را فقط به ADMIN_ID می‌فرستد.

    فرستنده یک تأیید کوتاه می‌گیرد. اگر نوع فایل غلط باشد یا دانلود بشکند،
    مدیر چیزی دریافت نمی‌کند.
    """
    name = str(document.get("file_name") or "")
    mime = str(document.get("mime_type") or "")
    markup = menu_keyboard(texts, is_admin)
    if not _is_xlsx(name, mime):
        await reply(texts["excel_bad_type"], markup)
        return
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
        converted = ctx.converter(data)
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

    # متن تبدیل‌شده برای خود فرستنده برنمی‌گردد؛ فقط مدیر فایل .txt را می‌گیرد.
    caption = render(
        texts["excel_admin_caption"],
        user_label=_user_label(user),
        user_id=user_id,
        filename=name or "upload.xlsx",
        rows=_line_count(converted),
    )
    try:
        await ctx.client.send_document(  # type: ignore[attr-defined]
            admin_id,
            text_filename(name),
            converted.encode("utf-8"),
            caption=caption,
            mime="text/plain; charset=utf-8",
            reply_markup=admin_keyboard(texts),
        )
    except Exception as exc:
        print("excel deliver failed:", type(exc).__name__)
        await reply(texts["excel_deliver_failed"], markup)
        return

    await reply(texts["excel_ack"], markup)
