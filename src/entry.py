"""نقطهٔ ورود ورکر پایتون روی کلادفلر.

ورکر برنامه‌ای است که روی سرور کلادفلر اجرا می‌شود و درخواست وب می‌گیرد.
بله پیام‌ها را به آدرس /webhook می‌فرستد. این فایل آن درخواست را می‌خواند،
باندینگ‌ها (TEXTS و DB) را برمی‌دارد و کار را به bot.handle_update می‌سپارد.

GET /health و GET / می‌گویند ورکر روشن است.
POST /set-webhook آدرس وب‌هوک را در بله ثبت می‌کند، به شرط وجود WEBHOOK_SECRET.

یک زمان‌بند دقیقه‌ای هم getUpdates را صدا می‌زند. این مسیر پشتیبان است، چون
گاهی دیوار کلادفلر (خطای ۱۰۱۰) درخواست وب‌هوک بله را قبل از رسیدن به این کد دور می‌ریزد.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from bale import BaleClient, BaleError, DryRunBale
from bot import BotContext, handle_update
from faq import FaqRepository
from routing import setup_authorized, webhook_authorized
from sample_loader import load_sample_xlsx
from state import StateRepository, UpdateDedupe
from storage import CloudflareKV
from texts import TextRepository
from users import D1UserStore

WEBHOOK_HEADER = "X-Webhook-Secret"
SETUP_HEADER = "X-Setup-Secret"


def _header(request: object, name: str) -> str:
    """یک هدر HTTP را می‌خواند. اگر نباشد رشتهٔ خالی برمی‌گردد، نه None."""
    headers = getattr(request, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    value = getter(name)
    if value is None:
        value = getter(name.lower())
    if value is None:
        return ""
    return str(value)


def _env_str(env: object, name: str) -> str:
    """متغیر محیط ورکر (توکن، شناسهٔ مدیر، …) را به رشتهٔ تمیز تبدیل می‌کند."""
    try:
        value = getattr(env, name)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _truthy(value: str) -> bool:
    """DRY_RUN و پرچم‌های مشابه فقط با این چند مقدار روشن حساب می‌شوند."""
    return value.lower() in {"1", "true", "yes", "on"}


async def _read_json(request: object) -> object:
    """بدنهٔ درخواست را JSON می‌کند. بدنهٔ خالی خطا است تا آپدیت جعلی ساخته نشود."""
    raw = await request.text()  # type: ignore[attr-defined]
    if not isinstance(raw, str):
        raw = str(raw)
    if not raw:
        raise ValueError("empty body")
    return json.loads(raw)


OFFSET_KEY = "bale:getupdates_offset"
# یک‌بار در هر اجرای ورکر هشدار می‌دهیم تا لاگ هر پیام پر از همین جمله نشود.
_db_missing_logged = False


def _binding(env: object, name: str) -> object | None:
    """باندینگ wrangler را برمی‌گرداند. نبودنش خطا نیست؛ تابع صداکننده تصمیم می‌گیرد."""
    try:
        value = getattr(env, name)
    except Exception:
        return None
    if value is None:
        return None
    return value


def _user_store(env: object) -> D1UserStore | None:
    """اگر باندینگ DB باشد مخزن کاربران را می‌سازد. بدون آن، بازو کار می‌کند ولی کسی ذخیره نمی‌شود."""
    global _db_missing_logged
    binding = _binding(env, "DB")
    if binding is None:
        if not _db_missing_logged:
            print("DB binding missing; user registry disabled")
            _db_missing_logged = True
        return None
    return D1UserStore(binding)


async def _build_context(env: object) -> tuple[BotContext, object, bool] | tuple[None, str, int]:
    """زمینهٔ گفتگو را می‌سازد. اگر توکن یا KV نباشد، به‌جای زمینه یک کد خطا برمی‌گردد."""
    kv_binding = _binding(env, "TEXTS")
    if kv_binding is None:
        return None, "missing_kv_binding", 500

    token = _env_str(env, "BALE_TOKEN")
    dry_run = _truthy(_env_str(env, "DRY_RUN"))
    if dry_run:
        client: object = DryRunBale()
    elif not token:
        return None, "missing_token", 500
    else:
        try:
            client = BaleClient(token)
        except BaleError:
            return None, "invalid_token", 500

    kv = CloudflareKV(kv_binding)
    context = BotContext(
        texts=TextRepository(kv),
        states=StateRepository(kv),
        dedupe=UpdateDedupe(kv),
        client=client,
        admin_id=_env_str(env, "ADMIN_ID"),
        load_sample=lambda: load_sample_xlsx(env),
        users=_user_store(env),
        # پرسش‌ها همان namespace متن‌ها را استفاده می‌کنند تا مدیر بدون استقرار عوضشان کند.
        faq=FaqRepository(kv),
        # خالی ماندن این‌ها یعنی متن debtor_* (پیش‌فرض نمونه). شعبهٔ شبا مهم نیست، فقط کد ۰۶۰.
        debtor_name=_env_str(env, "DEBTOR_NAME"),
        debtor_iban=_env_str(env, "DEBTOR_IBAN"),
        debtor_bic=_env_str(env, "DEBTOR_BIC"),
    )
    return context, client, dry_run


class Default(WorkerEntrypoint):
    """کلاسی که کلادفلر برای هر درخواست HTTP صدا می‌زند. نام Default قراردادی خود ورکر است."""

    async def fetch(self, request):
        path = urlparse(str(request.url)).path or "/"
        raw_method = getattr(request.method, "value", request.method)
        method = str(raw_method).upper()

        # سلامت‌سنج ساده برای اینکه بدانیم ورکر بالا است، بدون تماس با بله.
        if method == "GET" and path.rstrip("/") in {"", "/", "/health"}:
            return Response.json({"ok": True, "service": "bale-excel-bot"})

        if method == "POST" and (
            path.rstrip("/") == "/webhook" or path.startswith("/webhook/")
        ):
            return await self._webhook(request, path)

        if method == "POST" and path.rstrip("/") == "/set-webhook":
            return await self._set_webhook(request)

        return Response.json({"ok": False, "error": "not_found"}, status=404)

    async def scheduled(self, controller, env, ctx):
        """هر دقیقه آپدیت‌های نرسیده را از بله می‌گیرد.

        offset را در KV نگه می‌داریم تا دفعهٔ بعد همان پیام‌ها دوباره نیایند.
        پردازش هر آپدیت همان handle_update است، پس ثبت کاربر این‌جا هم انجام می‌شود.
        """
        built = await _build_context(self.env)
        if built[0] is None:
            print("cron skip:", built[1])
            return
        context, client, _dry_run = built  # type: ignore[misc]
        kv = context.states.kv  # type: ignore[attr-defined]
        # offset یعنی «آپدیت‌های کوچک‌تر از این شماره را دیگر نده».
        raw_offset = await kv.get(OFFSET_KEY)
        offset = int(raw_offset) if raw_offset and str(raw_offset).isdigit() else None
        try:
            updates = await client.get_updates(offset=offset, limit=50, timeout=0)  # type: ignore[attr-defined]
        except Exception as exc:
            print("cron getUpdates error:", type(exc).__name__)
            return
        if not isinstance(updates, list):
            print("cron getUpdates unexpected payload")
            return
        max_id = offset - 1 if offset else 0
        for update in updates:
            if not isinstance(update, dict):
                continue
            uid = update.get("update_id")
            if isinstance(uid, int) and uid > max_id:
                max_id = uid
            try:
                await handle_update(update, context)
            except Exception as exc:
                print("cron handler error:", type(exc).__name__, "update_id=", uid)
        if updates:
            # تا بزرگ‌ترین شناسه‌ای که دیدیم را تأیید می‌کنیم تا بله آن‌ها را از صف بردارد.
            await kv.put(OFFSET_KEY, str(max_id + 1))
            print("cron processed", len(updates), "next_offset", max_id + 1)

    async def _webhook(self, request, path: str):
        """آپدیت بله را می‌گیرد. اگر راز وب‌هوک تنظیم شده باشد، مسیر یا هدر باید همان را داشته باشد."""
        secret = _env_str(self.env, "WEBHOOK_SECRET")
        header = _header(request, WEBHOOK_HEADER)
        if not webhook_authorized(path, header, secret):
            return Response.json({"ok": False, "error": "unauthorized"}, status=401)

        try:
            update = await _read_json(request)
        except (ValueError, json.JSONDecodeError):
            return Response.json({"ok": False, "error": "bad_json"}, status=400)
        if not isinstance(update, dict):
            return Response.json({"ok": False, "error": "bad_json"}, status=400)

        built = await _build_context(self.env)
        if built[0] is None:
            return Response.json({"ok": False, "error": built[1]}, status=built[2])
        context, client, dry_run = built  # type: ignore[misc]
        try:
            await handle_update(update, context)
        except Exception as exc:
            print("webhook handler error:", type(exc).__name__)
            return Response.json({"ok": False, "error": "handler_error"}, status=500)

        if dry_run:
            return Response.json({"ok": True, "dry_run": True, "actions": client.actions})  # type: ignore[attr-defined]
        return Response.json({"ok": True})

    async def _set_webhook(self, request):
        """آدرس وب‌هوک را از طریق خود ورکر در بله ثبت می‌کند. بدون WEBHOOK_SECRET این مسیر بسته است."""
        secret = _env_str(self.env, "WEBHOOK_SECRET")
        if not setup_authorized(_header(request, SETUP_HEADER), secret):
            return Response.json({"ok": False, "error": "unauthorized"}, status=401)
        try:
            body = await _read_json(request)
        except (ValueError, json.JSONDecodeError):
            return Response.json({"ok": False, "error": "bad_json"}, status=400)
        if not isinstance(body, dict):
            return Response.json({"ok": False, "error": "bad_json"}, status=400)
        url = body.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            return Response.json({"ok": False, "error": "https_url_required"}, status=400)

        token = _env_str(self.env, "BALE_TOKEN")
        dry_run = _truthy(_env_str(self.env, "DRY_RUN"))
        try:
            if dry_run:
                client = DryRunBale()
                await client.set_webhook(url)
                return Response.json({"ok": True, "dry_run": True, "actions": client.actions})
            if not token:
                return Response.json({"ok": False, "error": "missing_token"}, status=500)
            result = await BaleClient(token).set_webhook(url)
        except BaleError as exc:
            print("setWebhook failed:", exc)
            return Response.json({"ok": False, "error": "bale_error"}, status=502)
        return Response.json({"ok": True, "result": result})
