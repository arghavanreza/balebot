"""متن‌های KV، عمر وضعیت گفتگو، و قفل مسیر وب‌هوک."""

import asyncio
import json

from bot import format_key_list
from routing import setup_authorized, webhook_authorized
from state import STATE_TTL_SECONDS, StateRepository, UpdateDedupe
from storage import MemoryKV
from texts import DEFAULT_TEXTS, TEXT_KEYS, TextRepository, _PREVIOUS_DEFAULTS, render


def _run(coro):
    return asyncio.run(coro)


def test_render_replaces_known_tokens_only():
    assert render("سلام {sheba}", sheba="IR1") == "سلام IR1"
    assert render("سلام {missing}", sheba="IR1") == "سلام {missing}"
    assert render("plain {", sheba="x") == "plain {"


def test_snapshot_seeds_and_update_keeps_other_keys():
    async def scenario():
        kv = MemoryKV()
        repo = TextRepository(kv)
        first = await repo.snapshot()
        assert first["btn_sheba"] == DEFAULT_TEXTS["btn_sheba"]
        assert "bot_texts" in kv.values
        await repo.update("welcome", "خوش آمدید")
        second = await repo.snapshot()
        assert second["welcome"] == "خوش آمدید"
        assert second["btn_sample"] == DEFAULT_TEXTS["btn_sample"]

    _run(scenario())


def test_new_key_is_merged_into_an_older_document():
    async def scenario():
        kv = MemoryKV()
        kv.values["bot_texts"] = '{"welcome": "سفارشی"}'
        repo = TextRepository(kv)
        snap = await repo.snapshot()
        assert snap["welcome"] == "سفارشی"
        assert snap["btn_sheba"] == DEFAULT_TEXTS["btn_sheba"]
        assert set(TEXT_KEYS) <= set(snap)

    _run(scenario())


def test_previous_default_labels_upgrade_and_custom_text_stays():
    """برچسب نسخهٔ قبل اگر دست‌نخورده باشد با متن مشتری‌پسند عوض می‌شود."""

    async def scenario():
        kv = MemoryKV()
        kv.values["bot_texts"] = json.dumps(
            {
                "welcome": "متن خود مدیر",
                "btn_sample": "دریافت سمپل اکسل",
                "btn_sheba": "بررسی شبا",
                "excel_admin_caption": (
                    "فایل تبدیل‌شده\n"
                    "کاربر: {user_label}\n"
                    "شناسه: {user_id}\n"
                    "نام فایل: {filename}\n"
                    "تعداد سطر: {rows}"
                ),
            },
            ensure_ascii=False,
        )
        snap = await TextRepository(kv).snapshot()
        assert snap["welcome"] == "متن خود مدیر"
        assert snap["btn_sample"] == DEFAULT_TEXTS["btn_sample"]
        assert snap["btn_sheba"] == DEFAULT_TEXTS["btn_sheba"]
        assert "📄" in snap["btn_sample"]
        assert "🏦" in snap["btn_sheba"]
        assert "{phone}" in snap["excel_admin_caption"]
        assert "موبایل" in snap["excel_admin_summary"]
        assert "تأیید" in snap["excel_upload_hint"]
        stored = json.loads(kv.values["bot_texts"])
        assert stored["welcome"] == "متن خود مدیر"
        assert stored["btn_sample"] == DEFAULT_TEXTS["btn_sample"]

    _run(scenario())


def test_plain_defaults_upgrade_to_emoji_copy_and_custom_text_stays():
    """پیش‌فرض بدون ایموجی مثل ویرایش‌نشده است. متن خود مدیر می‌ماند."""

    async def scenario():
        kv = MemoryKV()
        plain = {
            key: next(iter(values))
            for key, values in _PREVIOUS_DEFAULTS.items()
            if key in {"welcome", "btn_faq", "btn_cancel", "btn_share_phone", "phone_prompt", "excel_ack", "faq_intro", "cancelled"}
        }
        # برای کلیدهایی که چند پیش‌فرض قدیمی دارند، همان متنِ بلافاصله قبل از ایموجی را می‌گذاریم.
        plain["welcome"] = "سلام، به بازوی خدمات شعبهٔ بانک مهر خوش آمدید."
        plain["btn_sample"] = "نمونه فایل برای واریز حقوق"
        plain["btn_sheba"] = "اعتبارسنجی شبا"
        plain["sheba_prompt"] = "متن شبا که مدیر نوشته است"
        kv.values["bot_texts"] = json.dumps(plain, ensure_ascii=False)
        snap = await TextRepository(kv).snapshot()
        assert snap["welcome"] == DEFAULT_TEXTS["welcome"]
        assert snap["welcome"].startswith("👋")
        assert snap["btn_sample"] == DEFAULT_TEXTS["btn_sample"]
        assert snap["btn_sheba"] == DEFAULT_TEXTS["btn_sheba"]
        assert snap["btn_faq"] == DEFAULT_TEXTS["btn_faq"]
        assert snap["btn_cancel"] == DEFAULT_TEXTS["btn_cancel"]
        assert snap["btn_share_phone"] == DEFAULT_TEXTS["btn_share_phone"]
        assert snap["phone_prompt"] == DEFAULT_TEXTS["phone_prompt"]
        assert "منوی خدمات" in snap["phone_prompt"]
        assert snap["excel_ack"] == DEFAULT_TEXTS["excel_ack"]
        assert snap["faq_intro"] == DEFAULT_TEXTS["faq_intro"]
        assert snap["cancelled"] == DEFAULT_TEXTS["cancelled"]
        assert snap["sheba_prompt"] == "متن شبا که مدیر نوشته است"
        assert "phone_required" in snap
        stored = json.loads(kv.values["bot_texts"])
        assert stored["sheba_prompt"] == "متن شبا که مدیر نوشته است"
        assert stored["btn_back"] == DEFAULT_TEXTS["btn_back"]

    _run(scenario())


def test_admin_key_list_fits_in_one_message():
    assert len(format_key_list(DEFAULT_TEXTS)) < 3500


def test_state_ttl_and_dedupe():
    async def scenario():
        kv = MemoryKV()
        states = StateRepository(kv)
        await states.set("7", {"flow": "sheba"})
        assert kv.ttls["state:7"] == STATE_TTL_SECONDS
        assert (await states.get("7"))["flow"] == "sheba"
        await states.clear("7")
        assert await states.get("7") == {}

        dedupe = UpdateDedupe(kv)
        assert await dedupe.claim(10) is True
        assert await dedupe.claim(10) is False
        assert await dedupe.claim(None) is True

    _run(scenario())


def test_webhook_auth_without_secret():
    assert webhook_authorized("/webhook", None, "")
    assert webhook_authorized("/webhook/", None, None)
    assert not webhook_authorized("/webhook/abc", None, "")
    assert not setup_authorized("x", "")


def test_webhook_auth_with_secret():
    secret = "s3cret"
    assert webhook_authorized("/webhook/s3cret", None, secret)
    assert webhook_authorized("/webhook/s3cret/", "nope", secret)
    assert webhook_authorized("/webhook", "s3cret", secret)
    assert not webhook_authorized("/webhook", "nope", secret)
    assert not webhook_authorized("/webhook/nope", None, secret)
    assert not webhook_authorized("/webhook/s3cret/extra", None, secret)
    encoded = "a%2Fb"
    assert webhook_authorized(f"/webhook/{encoded}", None, "a/b")
    assert setup_authorized(secret, secret)
    assert not setup_authorized("other", secret)
