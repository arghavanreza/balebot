"""Small Bale Bot API client.

Calls `https://tapi.bale.ai` with JSON or raw multipart HTTPS. This does not
use python-telegram-bot (it is not a fit for the Workers runtime).

`DryRunBale` records the same methods and performs no network I/O. The Worker
uses it when `DRY_RUN=1`.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx

API_ROOT = "https://tapi.bale.ai"
USER_AGENT = "bale-excel-bot/0.1"
_TOKEN_IN_URL = re.compile(r"/bot[^/\s]+")


class BaleError(Exception):
    """Bale returned an error, or the HTTP call failed."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


def method_url(token: str, method: str) -> str:
    return f"{API_ROOT}/bot{token}/{method}"


def file_url(token: str, file_path: str) -> str:
    if file_path.startswith("https://") or file_path.startswith("http://"):
        return file_path
    return f"{API_ROOT}/file/bot{token}/{file_path.lstrip('/')}"


def redact_url(url: str) -> str:
    return _TOKEN_IN_URL.sub("/bot<token>", url)


def normalize_chat_id(chat_id: object) -> int | str:
    if isinstance(chat_id, int) and not isinstance(chat_id, bool):
        return chat_id
    text = str(chat_id).strip()
    if text.isdigit():
        return int(text)
    return text


def encode_multipart(
    fields: list[tuple[str, str]],
    files: list[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    """Build a multipart body. Filenames must be ASCII and quote-free."""
    boundary = "----bale" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                "\r\n"
            ).encode("utf-8")
            + value.encode("utf-8")
            + b"\r\n"
        )
    for name, filename, data, mime in files:
        safe_name = filename.replace('"', "").replace("\r", "").replace("\n", "")
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{safe_name}"\r\n'
                f"Content-Type: {mime}\r\n"
                "\r\n"
            ).encode("ascii")
            + data
            + b"\r\n"
        )
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def parse_api_response(status: int, body: str) -> Any:
    try:
        data = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise BaleError(f"non-json response ({status})", status=status) from exc
    if isinstance(data, dict) and data.get("ok") is False:
        description = data.get("description") or data.get("error") or "bale api error"
        raise BaleError(str(description), status=status, payload=data)
    if status >= 400:
        raise BaleError(f"http {status}", status=status, payload=data if isinstance(data, dict) else None)
    if isinstance(data, dict) and "ok" in data and "result" in data:
        return data["result"]
    return data


def _check_token(token: str) -> str:
    token = (token or "").strip()
    if not token or any(char.isspace() or char in "/?#" for char in token):
        raise BaleError("invalid bot token")
    return token


class BaleClient:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self.token = _check_token(token)
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout if timeout is None else timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def _post_json(self, method: str, payload: dict) -> Any:
        url = method_url(self.token, method)
        try:
            with self._client() as client:
                response = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise BaleError(f"{method} request failed") from exc
        return parse_api_response(response.status_code, response.text)

    async def send_message(self, chat_id: object, text: str, reply_markup: dict | None = None) -> Any:
        payload: dict[str, Any] = {"chat_id": normalize_chat_id(chat_id), "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self._post_json("sendMessage", payload)

    async def send_document(
        self,
        chat_id: object,
        filename: str,
        data: bytes,
        caption: str | None = None,
        mime: str | None = None,
        reply_markup: dict | None = None,
    ) -> Any:
        fields: list[tuple[str, str]] = [("chat_id", str(normalize_chat_id(chat_id)))]
        if caption:
            fields.append(("caption", caption))
        if reply_markup:
            fields.append(("reply_markup", json.dumps(reply_markup, ensure_ascii=False)))
        body, content_type = encode_multipart(
            fields,
            [("document", filename, data, mime or "application/octet-stream")],
        )
        url = method_url(self.token, "sendDocument")
        try:
            with self._client(timeout=60.0) as client:
                response = client.post(
                    url,
                    content=body,
                    headers={"Content-Type": content_type},
                )
        except httpx.HTTPError as exc:
            raise BaleError("sendDocument request failed") from exc
        return parse_api_response(response.status_code, response.text)

    async def get_file_bytes(self, file_id: str) -> bytes:
        result = self._post_json("getFile", {"file_id": file_id})
        if not isinstance(result, dict):
            raise BaleError("getFile returned no file")
        path = result.get("file_path") or result.get("filePath")
        if not path:
            raise BaleError("getFile returned no file_path")
        url = file_url(self.token, str(path))
        try:
            with self._client(timeout=60.0) as client:
                response = client.get(url)
        except httpx.HTTPError as exc:
            raise BaleError("file download failed") from exc
        if response.status_code >= 400:
            raise BaleError(f"file download failed ({response.status_code})", status=response.status_code)
        return response.content

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> Any:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        return self._post_json("answerCallbackQuery", payload)

    async def set_webhook(self, url: str) -> Any:
        return self._post_json("setWebhook", {"url": url})

    async def delete_webhook(self) -> Any:
        return self._post_json("deleteWebhook", {})

    async def get_updates(self, offset: int | None = None, limit: int = 100, timeout: int = 0) -> Any:
        payload: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._post_json("getUpdates", payload)


class DryRunBale:
    """Same surface as `BaleClient`, with the outgoing calls kept in `actions`."""

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []

    async def send_message(self, chat_id: object, text: str, reply_markup: dict | None = None) -> dict:
        self.actions.append(
            {
                "method": "sendMessage",
                "chat_id": normalize_chat_id(chat_id),
                "text": text,
                "reply_markup": reply_markup,
            }
        )
        return {"message_id": len(self.actions)}

    async def send_document(
        self,
        chat_id: object,
        filename: str,
        data: bytes,
        caption: str | None = None,
        mime: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        preview = ""
        if filename.endswith(".txt") or (mime or "").startswith("text/"):
            preview = data[:180].decode("utf-8", "replace")
        self.actions.append(
            {
                "method": "sendDocument",
                "chat_id": normalize_chat_id(chat_id),
                "filename": filename,
                "size": len(data),
                "caption": caption,
                "mime": mime,
                "reply_markup": reply_markup,
                "text_preview": preview,
            }
        )
        return {"message_id": len(self.actions)}

    async def get_file_bytes(self, file_id: str) -> bytes:
        raise BaleError(f"dry-run cannot download file {file_id}")

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> bool:
        self.actions.append(
            {
                "method": "answerCallbackQuery",
                "callback_query_id": callback_query_id,
                "text": text,
            }
        )
        return True

    async def set_webhook(self, url: str) -> bool:
        self.actions.append({"method": "setWebhook", "url": url})
        return True

    async def delete_webhook(self) -> bool:
        self.actions.append({"method": "deleteWebhook"})
        return True

    async def get_updates(self, offset: int | None = None, limit: int = 100, timeout: int = 0) -> list:
        self.actions.append(
            {"method": "getUpdates", "offset": offset, "limit": limit, "timeout": timeout}
        )
        return []
