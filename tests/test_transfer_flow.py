"""ویزارد انتقال تکی و رد شدن فایل گروهی، بدون شبکه."""

from io import BytesIO

from openpyxl import Workbook

from bot import handle_update
from sheba import iban_check_digits
from test_bot import ADMIN, USER, FakeBale, _ctx, _document, _run, _text
from texts import DEFAULT_TEXTS
from users import MemoryUserStore

OTHER = f"IR{iban_check_digits('IR', '012' + '0' * 18 + '2')}{'012' + '0' * 18 + '2'}"


def _labels(message: dict) -> list[str]:
    keyboard = message["reply_markup"]["keyboard"]
    return [button for row in keyboard for button in row]


def _bad_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["نام ذینفع", "شماره شبا / حساب ذینفع", "مبلغ"])
    sheet.append(["علی رضایی", "123", 0])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _callback(user_id: str, data: str, update_id: int) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cq-{update_id}",
            "from": {"id": int(user_id), "first_name": "علی", "username": "ali"},
            "data": data,
            "message": {"message_id": 1, "chat": {"id": int(user_id)}},
        },
    }


def test_customer_menu_has_transfer_buttons_and_group_upload_entry():
    async def scenario():
        client = FakeBale()
        await handle_update(_text(USER, "/start"), _ctx(client))
        labels = _labels(client.messages[0])
        assert DEFAULT_TEXTS["btn_sample"] in labels
        assert DEFAULT_TEXTS["btn_single"] in labels
        assert DEFAULT_TEXTS["btn_group"] in labels
        assert DEFAULT_TEXTS["btn_sheba"] in labels
        assert DEFAULT_TEXTS["btn_faq"] in labels
        assert "ارسال لیست انتقال وجه" not in labels

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_group"], update_id=2), _ctx(client))
        assert "انتقال وجه گروهی" in client.messages[-1]["text"]
        group_labels = _labels(client.messages[-1])
        assert DEFAULT_TEXTS["btn_group_send"] in group_labels
        assert DEFAULT_TEXTS["btn_sample"] in group_labels

    _run(scenario())


def test_single_transfer_confirm_notifies_admin_and_reject_does_not():
    async def scenario():
        client = FakeBale()
        store = MemoryUserStore()
        ctx = _ctx(client)
        ctx.users = store
        ctx.clock = lambda: "2026-10-01T10:00:00Z"
        await handle_update(_text(USER, "/start", update_id=1, username="ali"), ctx)
        await handle_update(_text(USER, "09121234567", update_id=2), ctx)

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_single"], update_id=3), ctx)
        assert "ذینفع" in client.messages[-1]["text"]
        await handle_update(_text(USER, "علی رضایی", update_id=4), ctx)
        await handle_update(_text(USER, "نه-این-حساب-نیست", update_id=5), ctx)
        assert "نامعتبر" in client.messages[-1]["text"] or "شبا" in client.messages[-1]["text"]
        await handle_update(_text(USER, OTHER, update_id=6), ctx)
        assert "مبلغ" in client.messages[-1]["text"]
        await handle_update(_text(USER, "۰", update_id=7), ctx)
        assert "ریال" in client.messages[-1]["text"]
        await handle_update(_text(USER, "۲۵۰۰۰۰", update_id=8), ctx)

        summary = client.messages[-1]
        assert "علی رضایی" in summary["text"]
        assert OTHER in summary["text"]
        assert "250000" in summary["text"]
        assert "پایا" in summary["text"]
        buttons = summary["reply_markup"]["inline_keyboard"][0]
        assert buttons[0]["text"] == "تایید"
        assert buttons[1]["text"] == "رد"
        reject_data = buttons[1]["callback_data"]
        confirm_data = buttons[0]["callback_data"]

        await handle_update(_callback(USER, reject_data, 9), ctx)
        assert "لغو" in client.messages[-1]["text"]
        assert not any(str(message["chat_id"]) == ADMIN for message in client.messages)

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_single"], update_id=10), ctx)
        await handle_update(_text(USER, "علی رضایی", update_id=11), ctx)
        await handle_update(_text(USER, OTHER, update_id=12), ctx)
        await handle_update(_text(USER, "250000", update_id=13), ctx)
        confirm_data = client.messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await handle_update(_callback(USER, confirm_data, 14), ctx)

        admin_messages = [message for message in client.messages if str(message["chat_id"]) == ADMIN]
        assert len(admin_messages) == 1
        notice = admin_messages[0]["text"]
        assert "انتقال وجه تکی" in notice
        assert USER in notice
        assert "علی رضایی" in notice
        assert OTHER in notice
        assert "250000" in notice
        assert "پایا" in notice
        assert "@ali" in notice
        assert "+989121234567" in notice
        assert "تهران" in notice
        user_messages = [message for message in client.messages if str(message["chat_id"]) == USER]
        assert "مدیر" in user_messages[-1]["text"]
        assert len(client.documents) == 1
        ccti = client.documents[0]
        assert str(ccti["chat_id"]) == ADMIN
        assert ccti["filename"].endswith(".ccti")
        xml = ccti["data"].decode("utf-8")
        assert OTHER in xml
        assert ">250000<" in xml
        assert "علی رضایی" in xml
        assert "EMPTY" in xml
        assert "BMJIIRTHXXX" in xml

        await handle_update(_callback(USER, confirm_data, 15), ctx)
        admin_again = [message for message in client.messages if str(message["chat_id"]) == ADMIN]
        assert len(admin_again) == 1
        assert "معتبر نیست" in client.messages[-1]["text"]

    _run(scenario())


def test_typed_reject_word_cancels_without_notifying_admin():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_single"], update_id=1), ctx)
        await handle_update(_text(USER, "سارا محمدی", update_id=2), ctx)
        await handle_update(_text(USER, "1234567890123", update_id=3), ctx)
        await handle_update(_text(USER, "3000000000", update_id=4), ctx)
        assert "داخلی" in client.messages[-1]["text"]
        await handle_update(_text(USER, "رد", update_id=5), ctx)
        assert "لغو" in client.messages[-1]["text"]
        assert client.messages[-1]["chat_id"] == int(USER)
        assert all(str(message["chat_id"]) != ADMIN for message in client.messages)

    _run(scenario())


def test_invalid_excel_stays_with_the_user():
    async def scenario():
        client = FakeBale(files={"file-1": _bad_xlsx()})
        ctx = _ctx(client)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_group"], update_id=1), ctx)
        await handle_update(_document(USER, update_id=2), ctx)
        assert client.documents == []
        assert not any(str(message["chat_id"]) == ADMIN for message in client.messages)
        assert "پذیرفته نشد" in client.messages[-1]["text"]
        assert "مدیر" in client.messages[-1]["text"]

    _run(scenario())
