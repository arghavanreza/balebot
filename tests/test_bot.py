"""جریان‌های گفتگو بدون شبکه: منو، شبا، اکسل، ویرایش متن.

کلاینت و KV ساختگی‌اند تا این تست‌ها به توکن بله یا کلادفلر نیاز نداشته باشند.
"""

import asyncio
from io import BytesIO

from openpyxl import Workbook

from bot import BotContext, handle_update, text_filename
from excel_convert import parse_workbook
from faq import FaqRepository
from state import StateRepository, UpdateDedupe
from storage import MemoryKV
from texts import DEFAULT_TEXTS, TextRepository
from users import MemoryUserStore

ADMIN = "42"
USER = "7"
VALID_SHEBA = "IR430120000000000000000001"


class FakeBale:
    def __init__(self, files=None, fail_send=False):
        self.files = files or {}
        self.fail_send = fail_send
        self.messages = []
        self.documents = []
        self.callbacks = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return {"message_id": len(self.messages)}

    async def send_document(self, chat_id, filename, data, caption=None, mime=None, reply_markup=None):
        if self.fail_send and str(chat_id) == ADMIN:
            raise RuntimeError("upstream down")
        self.documents.append(
            {
                "chat_id": chat_id,
                "filename": filename,
                "data": data,
                "caption": caption,
                "mime": mime,
                "reply_markup": reply_markup,
            }
        )
        return {"message_id": len(self.documents)}

    async def get_file_bytes(self, file_id):
        if file_id not in self.files:
            raise RuntimeError("missing")
        return self.files[file_id]

    async def answer_callback_query(self, callback_query_id, text=None):
        self.callbacks.append(callback_query_id)
        return True


def _run(coro):
    return asyncio.run(coro)


def _ctx(client, sample=b"PK-sample", admin_id=ADMIN, converter=None):
    kv = MemoryKV()

    async def load_sample():
        if sample is None:
            raise FileNotFoundError("missing")
        return sample

    context = BotContext(
        texts=TextRepository(kv),
        states=StateRepository(kv),
        dedupe=UpdateDedupe(kv),
        client=client,
        admin_id=admin_id,
        load_sample=load_sample,
        converter=converter or parse_workbook,
        faq=FaqRepository(kv),
    )
    return context


def _text(user_id, text, update_id=1, username=None):
    user = {"id": int(user_id), "first_name": "علی"}
    if username:
        user["username"] = username
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": user,
            "chat": {"id": int(user_id), "type": "private"},
            "text": text,
        },
    }


def _document(user_id, file_id="file-1", name="customers.xlsx", size=120, update_id=1, mime=None, username=None):
    update = _text(user_id, "", update_id=update_id, username=username)
    update["message"].pop("text")
    update["message"]["document"] = {
        "file_id": file_id,
        "file_name": name,
        "mime_type": mime
        or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "file_size": size,
    }
    return update


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["نام ذینفع", "شماره شبا / حساب ذینفع", "مبلغ"])
    sheet.append(["علی رضایی", VALID_SHEBA, 1500000])
    other = workbook.create_sheet("ignore-me")
    other.append(["SHOULD_NOT_APPEAR"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_start_user_and_admin_menus():
    async def scenario():
        client = FakeBale()
        await handle_update(_text(USER, "/start"), _ctx(client))
        text = client.messages[-1]["text"]
        assert "اکسل" in text
        keyboard = client.messages[-1]["reply_markup"]["keyboard"]
        labels = [button for row in keyboard for button in row]
        assert DEFAULT_TEXTS["btn_sample"] in labels
        assert DEFAULT_TEXTS["btn_sheba"] in labels
        assert DEFAULT_TEXTS["btn_edit"] not in labels

        await handle_update(_text(ADMIN, "/start@MyBot", update_id=2), _ctx(client))
        admin_text = client.messages[-1]["text"]
        assert "پنل مدیر" in admin_text
        admin_labels = [button for row in client.messages[-1]["reply_markup"]["keyboard"] for button in row]
        assert DEFAULT_TEXTS["btn_edit"] in admin_labels

    _run(scenario())


def test_sample_button_sends_xlsx_to_the_user():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client, sample=b"excel-bytes")
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sample"]), ctx)
        assert len(client.documents) == 1
        document = client.documents[0]
        assert document["chat_id"] == int(USER)
        assert document["filename"] == "sample.xlsx"
        assert document["data"] == b"excel-bytes"
        assert "ذینفع" in document["caption"]
        assert client.messages == []

    _run(scenario())


def test_sheba_flow_valid_invalid_and_retry():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sheba"], update_id=1), ctx)
        assert "شبا" in client.messages[-1]["text"]
        await handle_update(_text(USER, "IR000000000000000000000000", update_id=2), ctx)
        assert "نامعتبر" in client.messages[-1]["text"]
        # Still waiting, so a corrected number does not need the button again.
        await handle_update(_text(USER, "ir43 0120 0000 0000 0000 0000 01", update_id=3), ctx)
        assert "معتبر" in client.messages[-1]["text"]
        assert VALID_SHEBA in client.messages[-1]["text"]

    _run(scenario())


def test_excel_upload_goes_to_admin_as_text_and_user_is_acknowledged():
    async def scenario():
        payload = _xlsx_bytes()
        client = FakeBale(files={"file-1": payload})
        ctx = _ctx(client)
        update = _document(USER, update_id=5, username="ali")
        await handle_update(update, ctx)

        assert len(client.documents) == 1
        sent = client.documents[0]
        assert str(sent["chat_id"]) == ADMIN
        assert sent["filename"].endswith(".ccti")
        body = sent["data"].decode("utf-8")
        assert "CstmrCdtTrfInitn" in body
        assert "علی رضایی" in body
        assert VALID_SHEBA in body
        assert 'Ccy="IRR"' in body
        assert ">TRF<" in body
        assert "SHOULD_NOT_APPEAR" not in body
        assert "@ali" in sent["caption"]
        assert USER in sent["caption"]
        assert "تهران" in sent["caption"]
        user_messages = [message for message in client.messages if str(message["chat_id"]) == USER]
        admin_messages = [message for message in client.messages if str(message["chat_id"]) == ADMIN]
        assert user_messages
        assert "مدیر" in user_messages[-1]["text"]
        # The converted text is not echoed back to the sender.
        assert "name\tamount" not in user_messages[-1]["text"]
        assert admin_messages
        summary = admin_messages[-1]["text"]
        assert "خلاصه" in summary
        assert USER in summary
        assert "علی" in summary
        assert "@ali" in summary
        assert "ثبت نشده" in summary
        assert "تهران" in summary
        assert "سطر" in summary

    _run(scenario())


def test_rejects_non_xlsx_and_oversized_files():
    async def scenario():
        client = FakeBale(files={"file-1": b"data"})
        ctx = _ctx(client)
        await handle_update(
            _document(USER, name="notes.pdf", mime="application/pdf", update_id=1),
            ctx,
        )
        assert client.documents == []
        assert "xlsx" in client.messages[-1]["text"]

        await handle_update(
            _document(USER, size=21 * 1024 * 1024, update_id=2),
            ctx,
        )
        assert "۲۰ مگابایت" in client.messages[-1]["text"]
        assert client.documents == []

    _run(scenario())


def test_admin_can_edit_a_text_and_a_user_sees_it():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_update(_text(ADMIN, "ویرایش متن", update_id=1), ctx)
        assert "welcome" in client.messages[-1]["text"]
        await handle_update(_text(ADMIN, "welcome", update_id=2), ctx)
        assert "متن جدید" in client.messages[-1]["text"]
        await handle_update(_text(ADMIN, "درود بر شما", update_id=3), ctx)
        assert "ذخیره شد" in client.messages[-1]["text"]

        await handle_update(_text(USER, "/start", update_id=4), ctx)
        assert client.messages[-1]["text"].startswith("درود بر شما")

        await handle_update(_text(USER, "ویرایش متن", update_id=5), ctx)
        assert "فقط برای مدیر" in client.messages[-1]["text"]

    _run(scenario())


def test_duplicate_update_is_ignored():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_update(_text(USER, "/start", update_id=9), ctx)
        await handle_update(_text(USER, "/start", update_id=9), ctx)
        assert len(client.messages) == 1

    _run(scenario())


def test_custom_converter_is_used():
    async def scenario():
        client = FakeBale(files={"file-1": b"whatever"})

        def converter(_data: bytes) -> str:
            return "custom-row"

        ctx = _ctx(client, converter=converter)
        await handle_update(_document(USER, update_id=3), ctx)
        assert client.documents[0]["data"] == "custom-row".encode()

    _run(scenario())


def test_missing_admin_does_not_send_a_document():
    async def scenario():
        client = FakeBale(files={"file-1": _xlsx_bytes()})
        ctx = _ctx(client, admin_id="")
        await handle_update(_document(USER), ctx)
        assert client.documents == []
        assert "مدیر" in client.messages[-1]["text"]

    _run(scenario())


def test_text_filename_is_ascii():
    assert text_filename("گزارش نهایی.xlsx") == "sheet.txt"
    assert text_filename("Q1-payments.xlsx") == "Q1-payments.txt"


def test_messages_and_callbacks_are_stored_once_per_update():
    async def scenario():
        client = FakeBale()
        store = MemoryUserStore()
        times = iter(["2026-10-01T00:00:00Z", "2026-10-01T01:00:00Z"])
        ctx = _ctx(client)
        ctx.users = store
        ctx.clock = lambda: next(times)

        await handle_update(_text(USER, "/start", update_id=1, username="ali"), ctx)
        await handle_update(_text(USER, "/start", update_id=1, username="ali"), ctx)
        await handle_update(
            {
                "update_id": 2,
                "callback_query": {
                    "id": "cq-9",
                    "from": {"id": int(USER), "first_name": "علی", "username": "ali"},
                    "data": "x",
                },
            },
            ctx,
        )
        saved = store.by_id[int(USER)]
        assert saved.message_count == 2
        assert saved.first_seen_at == "2026-10-01T00:00:00Z"
        assert saved.last_seen_at == "2026-10-01T01:00:00Z"
        assert client.callbacks == ["cq-9"]

    _run(scenario())


def test_admin_users_command_and_failures_do_not_break_chat():
    async def scenario():
        client = FakeBale()
        store = MemoryUserStore()
        ctx = _ctx(client)
        ctx.users = store
        ctx.clock = lambda: "2026-10-01T00:00:00Z"
        await handle_update(_text(USER, "/start", update_id=1, username="ali"), ctx)
        await handle_update(_text(ADMIN, "/users", update_id=2), ctx)
        listing = client.messages[-1]["text"]
        assert "@ali" in listing
        assert USER in listing
        assert "کاربران اخیر" in listing

        await handle_update(_text(USER, "/users", update_id=3), ctx)
        assert "فقط برای مدیر" in client.messages[-1]["text"]

        class Boom:
            async def touch(self, profile):
                raise RuntimeError("no table")

            async def list_recent(self, limit=20):
                raise RuntimeError("no table")

        ctx.users = Boom()
        # /start قبلی جریان شماره را باز کرده؛ اول آن را می‌بندیم تا متن عادی همان پاسخ قبلی را بگیرد.
        await handle_update(_text(USER, "/cancel", update_id=4), ctx)
        await handle_update(_text(USER, "سلام", update_id=8), ctx)
        assert "متوجه نشدم" in client.messages[-1]["text"]
        await handle_update(_text(ADMIN, "/users", update_id=5), ctx)
        assert "فهرست کاربران" in client.messages[-1]["text"]

        ctx.users = None
        await handle_update(_text(ADMIN, "/users", update_id=6), ctx)
        assert "پایگاه کاربران وصل نیست" in client.messages[-1]["text"]

        fresh = MemoryUserStore()
        ctx.users = fresh
        await handle_update(
            {"update_id": 7, "message": {"chat": {"id": int(USER)}, "text": "/start"}},
            ctx,
        )
        assert fresh.by_id == {}
        assert client.messages

    _run(scenario())


def test_callback_is_answered():
    async def scenario():
        client = FakeBale()
        await handle_update(
            {"update_id": 1, "callback_query": {"id": "cq-1", "data": "unused"}},
            _ctx(client),
        )
        assert client.callbacks == ["cq-1"]

    _run(scenario())
