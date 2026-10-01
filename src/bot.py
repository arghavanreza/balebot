"""Conversation logic for the Bale bot.

The Worker entrypoint turns an Update into this module. Nothing here imports
the Workers runtime, so the flows can be unit-tested with an in-memory KV and
a fake Bale client.
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

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024

# Arabic Yeh/Kaf → Persian, and strip joiners that keyboards sometimes insert.
_LETTER_FOLD = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": "", "\u200d": ""})


@dataclass
class BotContext:
    texts: TextRepository
    states: StateRepository
    client: object
    admin_id: str
    load_sample: Callable[[], Awaitable[bytes]]
    converter: Callable[[bytes], str] = convert_excel_to_text
    dedupe: UpdateDedupe | None = None


def norm(text: str) -> str:
    return " ".join(text.translate(_LETTER_FOLD).split())


def command_name(text: str) -> str | None:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head = stripped.split()[0].split("@", 1)[0].lower()
    return head


def text_filename(original: str) -> str:
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
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def user_keyboard(texts: dict[str, str]) -> dict:
    return {"keyboard": [[texts["btn_sample"]], [texts["btn_sheba"]]]}


def admin_keyboard(texts: dict[str, str]) -> dict:
    return {
        "keyboard": [
            [texts["btn_edit"]],
            [texts["btn_sample"], texts["btn_sheba"]],
        ]
    }


def back_keyboard(texts: dict[str, str]) -> dict:
    return {"keyboard": [[texts["btn_back"]]]}


def cancel_keyboard(texts: dict[str, str]) -> dict:
    return {"keyboard": [[texts["btn_cancel"]]]}


def menu_keyboard(texts: dict[str, str], is_admin: bool) -> dict:
    return admin_keyboard(texts) if is_admin else user_keyboard(texts)


def match_button(text: str, texts: dict[str, str]) -> str | None:
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
    lines = [texts["admin_pick_prompt"], ""]
    for index, key in enumerate(TEXT_KEYS, start=1):
        lines.append(f"{index}. {key} — {KEY_HELP[key]}")
    return "\n".join(lines)


def _is_xlsx(name: str, mime: str) -> bool:
    if name.lower().endswith(".xlsx"):
        return True
    return mime.lower() == XLSX_MIME


def _user_label(user: dict) -> str:
    username = user.get("username")
    if isinstance(username, str) and username:
        return f"@{username}"
    parts = [user.get("first_name"), user.get("last_name")]
    name = " ".join(str(part) for part in parts if part)
    if name:
        return name
    return str(user.get("id") or "")


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


async def handle_update(update: dict, ctx: BotContext) -> None:
    if not isinstance(update, dict):
        return
    if ctx.dedupe is not None and not await ctx.dedupe.claim(update.get("update_id")):
        return

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        await _handle_callback(callback, ctx)
        return

    message = update.get("message")
    if isinstance(message, dict):
        await _handle_message(message, ctx)


async def _handle_callback(callback: dict, ctx: BotContext) -> None:
    callback_id = callback.get("id")
    if callback_id is None:
        return
    await ctx.client.answer_callback_query(str(callback_id))  # type: ignore[attr-defined]


async def _handle_message(message: dict, ctx: BotContext) -> None:
    user = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    user_id = str(user.get("id") or chat.get("id") or "")
    chat_id = chat.get("id", user.get("id"))
    if not user_id or chat_id is None:
        return

    admin_id = (ctx.admin_id or "").strip()
    is_admin = bool(admin_id) and user_id == admin_id
    texts = await ctx.texts.snapshot()

    async def reply(text: str, reply_markup: dict | None = None) -> None:
        body = (text or "").strip()
        if not body:
            return
        await ctx.client.send_message(chat_id, body, reply_markup=reply_markup)  # type: ignore[attr-defined]

    async def show_menu() -> None:
        if is_admin:
            await reply(texts["admin_intro"], admin_keyboard(texts))
            return
        parts = [texts["welcome"].strip()]
        hint = texts["welcome_hint"].strip()
        if hint:
            parts.append(hint)
        await reply("\n\n".join(part for part in parts if part), user_keyboard(texts))

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
        print(f"id user_id={user_id}")
        await reply(render(texts["id_reply"], user_id=user_id), menu_keyboard(texts, is_admin))
        return
    if command:
        await reply(texts["unknown_text"], menu_keyboard(texts, is_admin))
        return

    state = await ctx.states.get(user_id)
    flow = state.get("flow")

    # While a new string is being collected, only /commands (above) and the
    # cancel label interrupt. Any other text, including other button labels,
    # is the new value. Changing a string *to* the current cancel label needs
    # a temporary different cancel label first.
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

    await reply(texts["unknown_text"], menu_keyboard(texts, is_admin))


async def _save_text(
    raw_text: str,
    state: dict,
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    is_admin: bool,
    user_id: str,
) -> None:
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
    # Stay in the Sheba flow so the next message is another attempt.
    await reply(render(texts["sheba_invalid"], sheba=shown), cancel_keyboard(texts))


async def _send_sample(
    ctx: BotContext,
    texts: dict[str, str],
    reply: Callable[..., Awaitable[None]],
    chat_id: object,
    is_admin: bool,
) -> None:
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
