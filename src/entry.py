"""Cloudflare Python Worker entrypoint.

POST /webhook receives a Bale Update.
GET  /health (and GET /) reports that the Worker is up.
POST /set-webhook registers the webhook when WEBHOOK_SECRET is set.

A one-minute Cron Trigger also polls getUpdates. That is the reliability
path when Cloudflare Browser Integrity Check (error 1010) blocks Bale's
webhook User-Agent before the request reaches this Worker.
"""

from __future__ import annotations

import json
from urllib.parse import urlparse

from workers import Response, WorkerEntrypoint

from bale import BaleClient, BaleError, DryRunBale
from bot import BotContext, handle_update
from routing import setup_authorized, webhook_authorized
from sample_loader import load_sample_xlsx
from state import StateRepository, UpdateDedupe
from storage import CloudflareKV
from texts import TextRepository

WEBHOOK_HEADER = "X-Webhook-Secret"
SETUP_HEADER = "X-Setup-Secret"


def _header(request: object, name: str) -> str:
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
    try:
        value = getattr(env, name)
    except Exception:
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


async def _read_json(request: object) -> object:
    raw = await request.text()  # type: ignore[attr-defined]
    if not isinstance(raw, str):
        raw = str(raw)
    if not raw:
        raise ValueError("empty body")
    return json.loads(raw)


OFFSET_KEY = "bale:getupdates_offset"


async def _build_context(env: object) -> tuple[BotContext, object, bool] | tuple[None, str, int]:
    """Return (context, client, dry_run) or (None, error_code, http_status)."""
    kv_binding = getattr(env, "TEXTS", None)
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
    )
    return context, client, dry_run


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlparse(str(request.url)).path or "/"
        raw_method = getattr(request.method, "value", request.method)
        method = str(raw_method).upper()

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
        """Poll Bale getUpdates every minute (backup when webhook POSTs are blocked)."""
        built = await _build_context(self.env)
        if built[0] is None:
            print("cron skip:", built[1])
            return
        context, client, _dry_run = built  # type: ignore[misc]
        kv = context.states.kv  # type: ignore[attr-defined]
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
            # Confirm up to the highest seen id so Bale drops them from the queue.
            await kv.put(OFFSET_KEY, str(max_id + 1))
            print("cron processed", len(updates), "next_offset", max_id + 1)

    async def _webhook(self, request, path: str):
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
