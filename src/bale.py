"""کلاینت کوچک API بازوی بله.

همهٔ تماس‌ها به https://tapi.bale.ai می‌رود؛ پیام متنی با JSON و فایل با multipart.
از کتابخانهٔ تلگرام استفاده نمی‌کنیم چون با محیط ورکر پایتون جور نیست و بله هم
همان شکل درخواست را، روی دامنهٔ خودش، می‌خواهد.

DryRunBale همان متدها را دارد ولی به شبکه وصل نمی‌شود و کارها را در فهرست actions
نگه می‌دارد. ورکر وقتی DRY_RUN=1 باشد از همین کلاس استفاده می‌کند تا بشود محلی تست کرد.
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
    """بله خطا برگردانده یا خود تماس HTTP شکست خورده. متن توکن داخل این خطا نیست."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


def method_url(token: str, method: str) -> str:
    """آدرس یک متد، مثل sendMessage. توکن بخشی از مسیر است، نه هدر."""
    return f"{API_ROOT}/bot{token}/{method}"


def file_url(token: str, file_path: str) -> str:
    """آدرس دانلود فایل. getFile فقط مسیر نسبی می‌دهد و دانلود یک درخواست جداست."""
    if file_path.startswith("https://") or file_path.startswith("http://"):
        return file_path
    return f"{API_ROOT}/file/bot{token}/{file_path.lstrip('/')}"


def redact_url(url: str) -> str:
    """توکن را از آدرس برمی‌دارد تا اگر جایی لاگ شد، راز بازو لو نرود."""
    return _TOKEN_IN_URL.sub("/bot<token>", url)


def normalize_chat_id(chat_id: object) -> int | str:
    """شناسهٔ عددی را int می‌کند. بله شناسهٔ رشته‌ای عددی را هم می‌پذیرد ولی int مطمئن‌تر است."""
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
    """بدنهٔ multipart برای sendDocument. نام فایل باید ASCII و بدون گیومه باشد وگرنه هدر خراب می‌شود."""
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
    """جواب بله را می‌خواند. اگر ok برابر false باشد خطا می‌دهیم، حتی وقتی HTTP موفق به نظر برسد."""
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
    """توکن خالی یا توکنی که خودش مسیر URL را بشکند قبول نمی‌شود."""
    token = (token or "").strip()
    if not token or any(char.isspace() or char in "/?#" for char in token):
        raise BaleError("invalid bot token")
    return token


class BaleClient:
    """تماس واقعی با بله. توکن فقط این‌جا نگه داشته می‌شود و در لاگ چاپ نمی‌شود."""

    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self.token = _check_token(token)
        self.timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout if timeout is None else timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def _post_json(self, method: str, payload: dict) -> Any:
        # httpx این‌جا همگام است. تماس‌ها کوتاه‌اند و خطا را به BaleError تبدیل می‌کنیم
        # تا لایهٔ گفتگو به‌جای جزئیات شبکه، یک نوع خطای مشخص ببیند.

        url = method_url(self.token, method)
        try:
            with self._client() as client:
                response = client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise BaleError(f"{method} request failed") from exc
        return parse_api_response(response.status_code, response.text)

    async def send_message(self, chat_id: object, text: str, reply_markup: dict | None = None) -> Any:
        """یک پیام متنی. reply_markup همان کیبورد پایین چت است."""
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
        """ارسال فایل. اکسل تبدیل‌شده و نمونهٔ اکسل هر دو از این متد می‌روند."""
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
        """اول مسیر فایل را از getFile می‌گیرد، بعد خود بایت‌ها را دانلود می‌کند."""
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
        """چرخندهٔ روی دکمهٔ شیشه‌ای را می‌بندد. بدون این جواب، بله چند لحظه «در حال پردازش» نشان می‌دهد."""
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text[:200]
        return self._post_json("answerCallbackQuery", payload)

    async def set_webhook(self, url: str) -> Any:
        """به بله می‌گوید آپدیت‌ها را به این آدرس HTTPS بفرستد."""
        return self._post_json("setWebhook", {"url": url})

    async def delete_webhook(self) -> Any:
        """وب‌هوک را برمی‌دارد تا بشود دوباره با getUpdates صف را خواند."""
        return self._post_json("deleteWebhook", {})

    async def get_updates(self, offset: int | None = None, limit: int = 100, timeout: int = 0) -> Any:
        """آپدیت‌های نرسیده را می‌کشد. timeout صفر یعنی منتظر پیام تازه نمان؛ مناسب cron است."""
        payload: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        return self._post_json("getUpdates", payload)


class DryRunBale:
    """همان شکل BaleClient، بدون شبکه. هر فراخوانی در actions می‌ماند تا تست ببیند چه فرستاده می‌شد."""

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
