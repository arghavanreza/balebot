"""شمارهٔ موبایل، خلاصهٔ فایل برای مدیر، و دستور /stats.

پایگاه واقعی این‌جا نیست. MemoryUserStore همان قانون D1 را برای شماره و رویداد دارد.
"""

from bot import handle_update, phone_keyboard
from phone import normalize_phone
from stats import format_stats, format_tehran_stamp, tehran_day_bounds
from stats import StatsSnapshot
from test_bot import ADMIN, USER, FakeBale, _ctx, _document, _run, _text, _xlsx_bytes
from texts import DEFAULT_TEXTS
from users import MemoryUserStore


def test_normalize_phone_accepts_iran_mobile_shapes():
    assert normalize_phone("09121234567") == "+989121234567"
    assert normalize_phone("۰۹۱۲۱۲۳۴۵۶۷") == "+989121234567"
    assert normalize_phone("+98 912 123 4567") == "+989121234567"
    assert normalize_phone("00989121234567") == "+989121234567"
    assert normalize_phone("989121234567") == "+989121234567"
    assert normalize_phone("9121234567") == "+989121234567"
    assert normalize_phone("02112345678") is None
    assert normalize_phone("0912") is None
    assert normalize_phone("not-a-phone") is None
    assert normalize_phone(None) is None
    assert normalize_phone(True) is None


def test_tehran_day_starts_at_20_30_utc():
    # ۲۰:۳۰ UTC همان ۰۰:۰۰ روز بعد در تهران است، چون اختلاف همیشه ۳:۳۰ است.
    start, end, label = tehran_day_bounds("2026-10-01T10:00:00Z")
    assert label == "2026-10-01"
    assert start == "2026-09-30T20:30:00Z"
    assert end == "2026-10-01T20:30:00Z"
    next_start, _next_end, next_label = tehran_day_bounds("2026-10-01T20:30:00Z")
    assert next_label == "2026-10-02"
    assert next_start == "2026-10-01T20:30:00Z"
    stamp = format_tehran_stamp("2026-10-01T20:30:00Z")
    assert stamp.startswith("2026-10-02 00:00:00")
    assert "تهران" in stamp
    assert "2026-10-01T20:30:00Z" in stamp


def test_format_stats_defines_today_and_lists_faq():
    text = format_stats(
        StatsSnapshot(
            active_users=2,
            new_users=1,
            counts={"excel": 3, "faq": 4, "sheba": 0, "sample": 1},
            top_faq=[("مدارک افتتاح حساب چیست؟", 4)],
        ),
        day_label="2026-10-01",
    )
    assert "2026-10-01" in text
    assert "last_seen_at" in text
    assert "first_seen_at" in text
    assert "کاربران فعال امروز: 2" in text
    assert "ارسال اکسل امروز: 3" in text
    assert "مدارک افتتاح حساب چیست؟ — 4 بار" in text
    quiet = format_stats(
        StatsSnapshot(0, 0, {}, [], events_ready=False),
        day_label="2026-10-01",
    )
    assert "events" in quiet
    assert "ارسال اکسل" not in quiet


def test_phone_keyboard_requests_bale_contact():
    markup = phone_keyboard(DEFAULT_TEXTS)
    button = markup["keyboard"][0][0]
    assert button["request_contact"] is True
    assert button["text"] == DEFAULT_TEXTS["btn_share_phone"]
    labels = [row[0] if isinstance(row[0], str) else row[0]["text"] for row in markup["keyboard"]]
    assert DEFAULT_TEXTS["btn_sample"] in labels
    assert DEFAULT_TEXTS["btn_cancel"] in labels


def test_start_asks_for_phone_until_one_is_stored():
    async def scenario():
        client = FakeBale()
        store = MemoryUserStore()
        ctx = _ctx(client)
        ctx.users = store
        ctx.clock = lambda: "2026-10-01T10:00:00Z"

        await handle_update(_text(USER, "/start", update_id=1), ctx)
        prompt = client.messages[-1]
        assert "موبایل" in prompt["text"]
        assert prompt["reply_markup"]["keyboard"][0][0]["request_contact"] is True
        assert (await store.get(int(USER))).phone is None

        await handle_update(_text(USER, "0912", update_id=2), ctx)
        assert "نشناختم" in client.messages[-1]["text"]
        assert (await store.get(int(USER))).phone is None

        await handle_update(_text(USER, "۰۹۱۲۰۰۰۰۰۰۰", update_id=3), ctx)
        assert "+989120000000" in client.messages[-1]["text"]
        saved = await store.get(int(USER))
        assert saved.phone == "+989120000000"
        assert saved.last_action is None

        await handle_update(_text(USER, "/start", update_id=4), ctx)
        assert "موبایل" not in client.messages[-1]["text"]
        assert "خوش برگشتی" in client.messages[-1]["text"]

    _run(scenario())


def test_contact_share_stores_own_number_and_rejects_someone_else():
    async def scenario():
        client = FakeBale()
        store = MemoryUserStore()
        ctx = _ctx(client)
        ctx.users = store

        await handle_update(_text(USER, "/start", update_id=1), ctx)
        await handle_update(_contact(USER, "989121112233", update_id=2, owner=99), ctx)
        assert "خودتان" in client.messages[-1]["text"]
        assert (await store.get(int(USER))).phone is None

        await handle_update(_contact(USER, "09121112233", update_id=3, owner=int(USER)), ctx)
        assert (await store.get(int(USER))).phone == "+989121112233"
        assert "ثبت شد" in client.messages[-1]["text"]

    _run(scenario())


def test_phone_prompt_can_be_skipped_and_menu_still_works():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client, sample=b"excel-bytes")
        ctx.users = MemoryUserStore()
        await handle_update(_text(USER, "/start", update_id=1), ctx)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_cancel"], update_id=2), ctx)
        assert "start" in client.messages[-1]["text"]
        assert DEFAULT_TEXTS["btn_sample"] in _flat_labels(client.messages[-1])
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sample"], update_id=3), ctx)
        assert client.documents[-1]["filename"] == "sample.xlsx"
        assert (await ctx.users.get(int(USER))).phone is None
        assert (await ctx.users.get(int(USER))).last_action == "sample"

    _run(scenario())


def test_excel_summary_includes_stored_phone_and_file_still_goes_to_admin():
    async def scenario():
        client = FakeBale(files={"file-1": _xlsx_bytes()})
        store = MemoryUserStore()
        ctx = _ctx(client)
        ctx.users = store
        ctx.clock = lambda: "2026-10-01T10:00:00Z"
        await handle_update(_text(USER, "/start", update_id=1, username="ali"), ctx)
        await handle_update(_text(USER, "09121234567", update_id=2), ctx)

        update = _document(USER, update_id=3, username="ali")
        update["message"]["from"]["last_name"] = "رضایی"
        await handle_update(update, ctx)

        assert len(client.documents) == 1
        assert str(client.documents[0]["chat_id"]) == ADMIN
        assert client.documents[0]["filename"].endswith(".txt")
        summary = _admin_text(client)
        assert "شناسه: 7" in summary or f"شناسه: {USER}" in summary
        assert "علی" in summary
        assert "رضایی" in summary
        assert "@ali" in summary
        assert "+989121234567" in summary
        assert "2026-10-01 13:30:00" in summary
        assert "تهران" in summary
        assert "تعداد سطر خروجی: 2" in summary
        assert "+989121234567" in client.documents[0]["caption"]
        assert any("مدیر" in message["text"] for message in client.messages if str(message["chat_id"]) == USER)
        kinds = [event.kind for event in store.events]
        assert kinds.count("excel") == 1

    _run(scenario())


def test_excel_file_is_sent_when_summary_message_fails():
    async def scenario():
        client = _AdminMessageFails(files={"file-1": _xlsx_bytes()})
        ctx = _ctx(client)
        await handle_update(_document(USER, update_id=1, username="ali"), ctx)
        assert len(client.documents) == 1
        assert str(client.documents[0]["chat_id"]) == ADMIN
        assert any("مدیر" in message["text"] for message in client.messages)

    _run(scenario())


def test_stats_is_admin_only_and_counts_today():
    async def scenario():
        client = FakeBale(files={"file-1": _xlsx_bytes()})
        store = MemoryUserStore()
        ctx = _ctx(client, sample=b"excel-bytes")
        ctx.users = store
        ctx.clock = lambda: "2026-10-01T10:00:00Z"

        await handle_update(_text(USER, "/stats", update_id=1), ctx)
        assert "فقط برای مدیر" in client.messages[-1]["text"]

        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sheba"], update_id=2), ctx)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_sample"], update_id=3), ctx)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_faq"], update_id=4), ctx)
        await handle_update(_text(USER, "1", update_id=5), ctx)
        await handle_update(_document(USER, update_id=6), ctx)

        await handle_update(_text(ADMIN, "/stats", update_id=7), ctx)
        report = client.messages[-1]["text"]
        assert "آمار امروز" in report
        assert "2026-10-01" in report
        # خود دستور /stats هم مدیر را در پایگاه می‌نویسد، پس امروز دو نفر فعال‌اند.
        assert "کاربران فعال امروز: 2" in report
        assert "کاربران تازه‌وارد امروز: 2" in report
        assert "ارسال اکسل امروز: 1" in report
        assert "نمونهٔ فایل امروز: 1" in report
        assert "شروع اعتبارسنجی شبا امروز: 1" in report
        assert "باز شدن پاسخ پرسش امروز: 1" in report
        assert "مدارک افتتاح حساب چیست؟" in report

        ctx.users = None
        await handle_update(_text(ADMIN, "/stats", update_id=8), ctx)
        assert "پایگاه آمار وصل نیست" in client.messages[-1]["text"]

    _run(scenario())


class _AdminMessageFails(FakeBale):
    async def send_message(self, chat_id, text, reply_markup=None):
        if str(chat_id) == ADMIN:
            raise RuntimeError("summary down")
        self.messages.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
        return {"message_id": len(self.messages)}


def _contact(user_id, phone, update_id, owner=None):
    update = _text(user_id, "", update_id=update_id)
    update["message"].pop("text")
    contact = {"phone_number": phone, "first_name": "علی"}
    if owner is not None:
        contact["user_id"] = owner
    update["message"]["contact"] = contact
    return update


def _admin_text(client: FakeBale) -> str:
    for message in reversed(client.messages):
        if str(message["chat_id"]) == ADMIN:
            return message["text"]
    raise AssertionError("admin summary missing")


def _flat_labels(message: dict) -> list[str]:
    labels = []
    for row in message["reply_markup"]["keyboard"]:
        for button in row:
            labels.append(button if isinstance(button, str) else button.get("text"))
    return labels
