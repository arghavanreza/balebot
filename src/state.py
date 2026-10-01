"""Short-lived conversation state, keyed by Bale user id.

Flows (awaiting a Sheba, picking a text key, awaiting the new text) are a
small JSON document. A new state overwrites the previous one. TTL is 30
minutes, which is above KV's 60-second minimum.
"""

from __future__ import annotations

import json

from texts import KeyValue

STATE_TTL_SECONDS = 30 * 60
DEDUPE_TTL_SECONDS = 60 * 60


class StateRepository:
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
    """Remember `update_id` for an hour so a webhook retry does not send twice."""

    def __init__(self, kv: KeyValue) -> None:
        self.kv = kv

    async def claim(self, update_id: object) -> bool:
        if update_id is None:
            return True
        key = f"update:{update_id}"
        if await self.kv.get(key):
            return False
        await self.kv.put(key, "1", ttl=DEDUPE_TTL_SECONDS)
        return True
