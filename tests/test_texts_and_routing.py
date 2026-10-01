"""متن‌های KV، عمر وضعیت گفتگو، و قفل مسیر وب‌هوک."""

import asyncio
import json

from bot import format_key_list
from routing import setup_authorized, webhook_authorized
from state import STATE_TTL_SECONDS, StateRepository, UpdateDedupe
from storage import MemoryKV
from texts import DEFAULT_TEXTS, TEXT_KEYS, TextRepository, render


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
            },
            ensure_ascii=False,
        )
        snap = await TextRepository(kv).snapshot()
        assert snap["welcome"] == "متن خود مدیر"
        assert snap["btn_sample"] == "نمونه فایل برای واریز حقوق"
        assert snap["btn_sheba"] == "اعتبارسنجی شبا"
        assert "تأیید" in snap["excel_upload_hint"]
        stored = json.loads(kv.values["bot_texts"])
        assert stored["welcome"] == "متن خود مدیر"
        assert stored["btn_sample"] == DEFAULT_TEXTS["btn_sample"]

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
