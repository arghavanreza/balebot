"""مسیر پرسش‌های متداول و خوش‌آمد شخصی، بدون شبکه."""

import json

import pytest

from bot import handle_update
from faq import DEFAULT_FAQ, FaqFullError, FaqItem, FaqRepository
from storage import MemoryKV
from test_bot import ADMIN, USER, FakeBale, _ctx, _document, _run, _text, _xlsx_bytes
from texts import DEFAULT_TEXTS
from users import MemoryUserStore


def test_customer_menu_has_friendly_labels_and_upload_hint_before_the_file():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_start(client, ctx, USER, update_id=1)
        text = client.messages[-1]["text"]
        assert "فایل اکسل" in text
        assert "تأیید" in text
        assert "مدیر شعبه" in text
        labels = _labels(client.messages[-1])
        assert DEFAULT_TEXTS["btn_sample"] in labels
        assert DEFAULT_TEXTS["btn_sheba"] in labels
        assert DEFAULT_TEXTS["btn_faq"] in labels
        assert DEFAULT_TEXTS["btn_faq_edit"] not in labels
        assert client.documents == []

        client.files = {"file-1": _xlsx_bytes()}
        await handle_update(_document(USER, update_id=2), ctx)
        assert client.documents[0]["filename"].endswith(".ccti")
        assert str(client.documents[0]["chat_id"]) == ADMIN
        assert "مدیر" in client.messages[-1]["text"]

    _run(scenario())


def test_faq_number_answer_back_and_main_menu():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_faq"], update_id=1), ctx)
        listing = client.messages[-1]["text"]
        assert "مدارک افتتاح حساب" in listing
        assert "سقف انتقال" in listing
        assert DEFAULT_TEXTS["btn_back"] in _labels(client.messages[-1])

        await handle_update(_text(USER, "۲", update_id=2), ctx)
        answer = client.messages[-1]["text"]
        assert "پایا" in answer
        assert DEFAULT_TEXTS["btn_faq_back"] in _labels(client.messages[-1])

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_faq_back"], update_id=3), ctx)
        assert "مدارک افتتاح حساب" in client.messages[-1]["text"]

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_back"], update_id=4), ctx)
        assert DEFAULT_TEXTS["btn_sample"] in _labels(client.messages[-1])

        # بیرون از فهرست، شمارهٔ تنها نباید اولین پاسخ را باز کند.
        await handle_update(_text(USER, "1", update_id=5), ctx)
        assert "متوجه نشدم" in client.messages[-1]["text"]

    _run(scenario())


def test_admin_can_edit_add_and_delete_faq_without_redeploy():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        await handle_update(_text(ADMIN, DEFAULT_TEXTS["btn_faq_edit"], update_id=1), ctx)
        assert "جدید" in client.messages[-1]["text"]

        await handle_update(_text(ADMIN, "1", update_id=2), ctx)
        assert "متن پرسش" in client.messages[-1]["text"]
        await handle_update(_text(ADMIN, "سؤال شعبه؟", update_id=3), ctx)
        assert "متن پاسخ" in client.messages[-1]["text"]
        await handle_update(_text(ADMIN, "پاسخ شعبه.", update_id=4), ctx)
        assert "ذخیره شد" in client.messages[-1]["text"]
        assert "سؤال شعبه؟" in client.messages[-1]["text"]

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_faq"], update_id=5), ctx)
        await handle_update(_text(USER, "1", update_id=6), ctx)
        assert "پاسخ شعبه" in client.messages[-1]["text"]

        await handle_update(_text(ADMIN, DEFAULT_TEXTS["btn_faq_edit"], update_id=7), ctx)
        await handle_update(_text(ADMIN, "جدید", update_id=8), ctx)
        await handle_update(_text(ADMIN, "پرسش اضافه؟", update_id=9), ctx)
        await handle_update(_text(ADMIN, "پاسخ اضافه.", update_id=10), ctx)
        assert "پرسش اضافه؟" in client.messages[-1]["text"]

        await handle_update(_text(ADMIN, "حذف۱", update_id=11), ctx)
        assert "حذف شد" in client.messages[-1]["text"]
        assert "سؤال شعبه؟" not in client.messages[-1]["text"]

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_faq_edit"], update_id=12), ctx)
        assert "فقط برای مدیر" in client.messages[-1]["text"]

        # حذف پیش‌فرض در hidden می‌ماند و با خواندن دوباره برنمی‌گردد.
        again = FaqRepository(ctx.faq.kv)
        ids = [item.id for item in await again.list_items()]
        assert "open-account" not in ids
        assert any(item_id.startswith("custom-") for item_id in ids)

    _run(scenario())


def test_deleted_default_stays_hidden_and_new_default_is_merged():
    async def scenario():
        kv = MemoryKV()
        kv.values["bot_faq"] = json.dumps(
            {
                "items": [{"id": "custom-9", "question": "سؤال محلی؟", "answer": "جواب محلی."}],
                "hidden": ["hours"],
            },
            ensure_ascii=False,
        )
        items = await FaqRepository(kv).list_items()
        ids = [item.id for item in items]
        assert ids[0] == "custom-9"
        assert "hours" not in ids
        assert "open-account" in ids
        assert len(DEFAULT_FAQ) == 8

    _run(scenario())


def test_unchanged_payroll_faq_upgrades_and_a_custom_answer_stays():
    async def scenario():
        kv = MemoryKV()
        old_answer = (
            "دکمهٔ «نمونه فایل برای واریز حقوق» را بزنید. "
            "ستون‌های name (نام)، amount (مبلغ به ریال) و sheba را پر کنید و فایل xlsx را در همین گفتگو بفرستید. "
            "شما یک پیام تأیید می‌گیرید و متن فایل برای مسئول شعبه ارسال می‌شود."
        )
        kv.values["bot_faq"] = json.dumps(
            {
                "items": [
                    {
                        "id": "payroll-file",
                        "question": "فایل حقوق را چطور بفرستم؟",
                        "answer": old_answer,
                    },
                    {
                        "id": "limits",
                        "question": "سقف شعبه؟",
                        "answer": "جواب خود شعبه.",
                    },
                ],
                "hidden": [],
            },
            ensure_ascii=False,
        )
        items = await FaqRepository(kv).list_items()
        by_id = {item.id: item for item in items}
        assert "نام ذینفع" in by_id["payroll-file"].answer
        assert by_id["limits"].answer == "جواب خود شعبه."

    _run(scenario())


def test_faq_repository_refuses_an_eleventh_item():
    async def scenario():
        repo = FaqRepository(MemoryKV())
        await repo.list_items()
        await repo.upsert(FaqItem("custom-1", "س۱؟", "ج۱"))
        await repo.upsert(FaqItem("custom-2", "س۲؟", "ج۲"))
        with pytest.raises(FaqFullError):
            await repo.upsert(FaqItem("custom-3", "س۳؟", "ج۳"))

    _run(scenario())


def test_start_welcomes_by_name_then_returns_without_inventing_history():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        ctx.users = MemoryUserStore()

        await handle_update(_text(USER, "/start", update_id=1), ctx)
        first = _latest_greeting(client.messages)
        assert "علی" in first
        assert "خوش آمدید" in first
        assert "خوش برگشتی" not in first
        assert "دفعهٔ قبل" not in first
        # شماره بعد از خوش‌آمد پرسیده می‌شود و جای خود خوش‌آمد را نمی‌گیرد.
        assert "موبایل" in client.messages[-1]["text"]

        await handle_update(_text(USER, "/start", update_id=2), ctx)
        again = _latest_greeting(client.messages)
        assert "خوش برگشتی" in again
        assert "علی" in again
        assert "دفعهٔ قبل" not in again
        assert "موبایل" in client.messages[-1]["text"]

        # بدون شماره، دکمهٔ شبا موضوع خوش‌آمد نمی‌سازد.
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sheba"], update_id=3), ctx)
        assert (await ctx.users.get(int(USER))).last_action is None
        await handle_update(_text(USER, "09120000000", update_id=4), ctx)
        await handle_update(_text(USER, "علی رضایی", update_id=5), ctx)
        await handle_update(_text(USER, "1234567891", update_id=6), ctx)

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sheba"], update_id=7), ctx)
        await handle_update(_text(USER, "/start", update_id=8), ctx)
        topic = _latest_greeting(client.messages)
        assert "خوش برگشتی" in topic
        assert DEFAULT_TEXTS["btn_sheba"] in topic

        client.files = {"file-1": _xlsx_bytes()}
        await handle_update(_document(USER, update_id=9), ctx)
        await handle_update(_text(USER, "/start", update_id=10), ctx)
        assert DEFAULT_TEXTS["topic_excel"] in _latest_greeting(client.messages)

    _run(scenario())


def test_start_without_a_name_and_when_d1_fails_stays_generic():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        ctx.users = MemoryUserStore()
        nameless = _text(USER, "/start", update_id=1)
        nameless["message"]["from"].pop("first_name")
        await handle_update(nameless, ctx)
        assert _latest_greeting(client.messages).startswith(DEFAULT_TEXTS["welcome"])
        assert "موبایل" in client.messages[-1]["text"]

        nameless_again = _text(USER, "/start", update_id=2)
        nameless_again["message"]["from"].pop("first_name")
        await handle_update(nameless_again, ctx)
        returned = _latest_greeting(client.messages)
        assert "خوش برگشتی" in returned
        assert "علی" not in returned
        assert "دفعهٔ قبل" not in returned

        class Boom:
            async def touch(self, profile):
                raise RuntimeError("d1 down")

            async def get(self, user_id):
                raise RuntimeError("d1 down")

            async def list_recent(self, limit=20):
                raise RuntimeError("d1 down")

            async def set_last_action(self, user_id, action):
                raise RuntimeError("d1 down")

        ctx.users = Boom()
        await handle_update(_text(USER, "/start", update_id=3), ctx)
        generic = client.messages[-1]["text"]
        assert generic.startswith(DEFAULT_TEXTS["welcome"])
        assert "خوش برگشتی" not in generic

        await handle_update(_text(ADMIN, "/start", update_id=4), ctx)
        assert "پنل مدیر" in client.messages[-1]["text"]
        assert DEFAULT_TEXTS["btn_faq_edit"] in _labels(client.messages[-1])

    _run(scenario())


def _latest_greeting(messages: list[dict]) -> str:
    """آخرین خوش‌آمد را برمی‌گرداند. درخواست شماره ممکن است بعد از آن آمده باشد."""
    for message in reversed(messages):
        text = message["text"]
        if "خوش آمدید" in text or "خوش برگشتی" in text:
            return text
    raise AssertionError("greeting missing")


def _labels(message: dict) -> list[str]:
    keyboard = message["reply_markup"]["keyboard"]
    return [button for row in keyboard for button in row]


def handle_start(client, ctx, user_id, update_id):
    return handle_update(_text(user_id, "/start", update_id=update_id), ctx)
