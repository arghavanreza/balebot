"""Key/value adapters used by texts, conversation state, and update de-dupe.

`MemoryKV` is for unit tests. `CloudflareKV` wrapps a Workers KV binding.
"""

from __future__ import annotations


class MemoryKV:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def put(self, key: str, value: str, ttl: int | None = None) -> None:
        self.values[key] = value
        self.ttls[key] = ttl

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)


class CloudflareKV:
    """Workers KV binding. `expirationTtl` is in seconds and must be at least 60."""

    def __init__(self, binding: object) -> None:
        self.binding = binding

    async def get(self, key: str) -> str | None:
        value = await self.binding.get(key)  # type: ignore[attr-defined]
        if value is None:
            return None
        return str(value)

    async def put(self, key: str, value: str, ttl: int | None = None) -> None:
        # KV's JS API takes an options object, not a keyword argument:
        # put(key, value, { expirationTtl }). Minimum TTL is 60 seconds.
        if ttl is None:
            await self.binding.put(key, value)  # type: ignore[attr-defined]
        else:
            await self.binding.put(key, value, {"expirationTtl": int(ttl)})  # type: ignore[attr-defined]

    async def delete(self, key: str) -> None:
        await self.binding.delete(key)  # type: ignore[attr-defined]
