"""وضعیت کوتاه گفتگو، با کلید شناسهٔ کاربر بله.

وقتی بازو منتظر شبا، انتخاب کلید، یا متن جدید است، یک JSON کوچک در KV می‌نویسد.
وضعیت تازه، قبلی را پاک می‌کند؛ هم‌زمان دو جریان باز نمی‌ماند.
عمر وضعیت ۳۰ دقیقه است. این عدد از حداقل ۶۰ ثانیهٔ KV بیشتر است
تا گفتگوی رهاشده تا ابد در حافظه نماند.
"""

from __future__ import annotations

import json

from texts import KeyValue

STATE_TTL_SECONDS = 30 * 60
DEDUPE_TTL_SECONDS = 60 * 60


class StateRepository:
    """خواندن و نوشتن جریان فعلی یک کاربر. کلیدها به شکل state:<شناسه> هستند."""

    def __init__(self, kv: KeyValue) -> None:
        self.kv = kv

    def _key(self, user_id: str) -> str:
        return f"state:{user_id}"

    async def get(self, user_id: str) -> dict:
        raw = await self.kv.get(self._key(user_id))
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    async def set(self, user_id: str, state: dict) -> None:
        await self.kv.put(
            self._key(user_id),
            json.dumps(state, ensure_ascii=False),
            ttl=STATE_TTL_SECONDS,
        )

    async def clear(self, user_id: str) -> None:
        await self.kv.delete(self._key(user_id))


class UpdateDedupe:
    """شناسهٔ آپدیت را یک ساعت نگه می‌دارد تا تلاش دوبارهٔ بله همان جواب را دو بار نفرستد."""

    def __init__(self, kv: KeyValue) -> None:
        self.kv = kv

    async def claim(self, update_id: object) -> bool:
        # بدون شناسه نمی‌شود تکراری را شناخت؛ پردازش را رد نمی‌کنیم.
        if update_id is None:
            return True
        key = f"update:{update_id}"
        if await self.kv.get(key):
            return False
        await self.kv.put(key, "1", ttl=DEDUPE_TTL_SECONDS)
        return True
