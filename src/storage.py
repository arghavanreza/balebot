"""رابط کلید/مقدار برای متن‌ها، وضعیت گفتگو و جلوگیری از پردازش دوباره.

خود بازو مستقیم به KV کلادفلر وصل نیست. MemoryKV در تست‌ها جای پایگاه را می‌گیرد
و CloudflareKV همان متدها را به باندینگ واقعی TEXTS وصل می‌کند.
اگر امضای get/put/delete یکی بماند، بقیهٔ کد فرق این دو را نمی‌فهمد.
"""

from __future__ import annotations


class MemoryKV:
    """دیکشنری داخل حافظه. فقط برای pytest است و با خاموش شدن برنامه پاک می‌شود."""

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
    """باندینگ KV ورکر. expirationTtl به ثانیه است و کلادفلر کمتر از ۶۰ ثانیه را نمی‌پذیرد."""

    def __init__(self, binding: object) -> None:
        self.binding = binding

    async def get(self, key: str) -> str | None:
        value = await self.binding.get(key)  # type: ignore[attr-defined]
        if value is None:
            return None
        return str(value)

    async def put(self, key: str, value: str, ttl: int | None = None) -> None:
        # رابط جاوااسکریپت KV آرگومان نام‌دار نمی‌گیرد؛ گزینه‌ها یک شیء جدا هستند.
        # کمترین عمر مجاز ۶۰ ثانیه است. بدون ttl مقدار می‌ماند تا خودمان پاکش کنیم.
        if ttl is None:
            await self.binding.put(key, value)  # type: ignore[attr-defined]
        else:
            await self.binding.put(key, value, {"expirationTtl": int(ttl)})  # type: ignore[attr-defined]

    async def delete(self, key: str) -> None:
        await self.binding.delete(key)  # type: ignore[attr-defined]
