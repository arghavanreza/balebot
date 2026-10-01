"""منطق گفتگوی بازو.

ورکر هر آپدیت بله را به handle_update می‌دهد. این فایل به محیط کلادفلر وصل نیست
تا بشود جریان‌ها را با حافظهٔ ساختگی و کلاینت ساختگی تست کرد.

کارهایی که این‌جا انجام می‌شود: منوی کاربر و مدیر، نمونهٔ اکسل، اعتبارسنجی شبا،
پرسش‌های متداول شعبه، ویرایش متن، تبدیل فایل اکسل و فرستادن نتیجه فقط برای مدیر،
ثبت کاربر در D1، و خوش‌آمد با نام اگر پایگاه در دسترس باشد.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from excel_convert import ExcelConvertError, convert_excel_to_text
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
    converter: Callable[[bytes], str] = convert_excel_to_text
    dedupe: UpdateDedupe | None = None
    users: UserStore | None = None
    clock: Callable[[], str] = utc_now_iso
    # پرسش‌ها روی همان KV متن‌ها هستند، ولی سند جدا دارند. None یعنی این بخش خاموش است.
    faq: FaqRepository | None = None


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
    """کیبورد مشتری: نمونهٔ فایل حقوق، اعتبارسنجی شبا، پرسش‌های متداول.

    هر برچسب یک ردیف است چون «نمونه فایل برای واریز حقوق» در ردیف مشترک جا نمی‌شود.
    """
    return {
        "keyboard": [
            [texts["btn_sample"]],
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
            [texts["btn_sheba"]],
            [texts["btn_faq"]],
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

    async def show_menu(personal: bool = False) -> None:
        # خوش‌آمد مدیر و کاربر جداست تا مشتری دکمهٔ ویرایش متن را نبیند.
        # personal فقط برای /start است تا «خوش برگشتی» وسط انصراف تکرار نشود.
        if is_admin:
            await reply(texts["admin_intro"], admin_keyboard(texts))
            return
        profile = await _load_profile(ctx, user_id) if personal else None
        await reply(compose_customer_text(texts, profile), user_keyboard(texts))

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
        await show_menu(personal=True)
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
        await _send_sample(ctx, texts, reply, chat_id, is_admin)
        return
    if action == "sheba":
        await ctx.states.set(user_id, {"flow": "sheba"})
        await _note_action(ctx, user_id, "sheba")
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
