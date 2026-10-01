"""خواندن فایل نمونهٔ اکسل.

ترتیب عمدی است: اگر R2 را روشن کرده باشید همان اولویت دارد، وگرنه دارایی ثابت
کنار ورکر، و در نهایت فایل روی دیسک. دیسک برای pytest و برای وقتی است که
خواندن دارایی در توسعهٔ محلی شکست بخورد. مشتری نباید به‌خاطر جای فایل، نمونه را از دست بدهد.
"""

from __future__ import annotations

from pathlib import Path

SAMPLE_NAME = "sample.xlsx"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def disk_candidates() -> list[Path]:
    """چند مسیر محتمل، چون تست از ریشه اجرا می‌شود و ورکر گاهی از پوشهٔ دیگری بالا می‌آید."""
    here = Path(__file__).resolve()
    return [
        here.parent.parent / "assets" / SAMPLE_NAME,
        here.parent / SAMPLE_NAME,
        Path.cwd() / "assets" / SAMPLE_NAME,
    ]


def read_sample_from_disk() -> bytes:
    """اولین sample.xlsx موجود روی دیسک. اگر هیچ‌کدام نباشد خطا می‌دهیم تا سکوت، فایل خالی نفرستد."""
    for path in disk_candidates():
        if path.is_file():
            return path.read_bytes()
    raise FileNotFoundError("sample.xlsx was not found on disk")


def buffer_to_bytes(buf: object) -> bytes:
    """خروجی جاوااسکریپت (ArrayBuffer) یا bytes پایتون را به bytes یکدست تبدیل می‌کند."""
    if isinstance(buf, (bytes, bytearray, memoryview)):
        return bytes(buf)
    to_bytes = getattr(buf, "to_bytes", None)
    if callable(to_bytes):
        return bytes(to_bytes())
    from js import Uint8Array

    view = Uint8Array.new(buf)
    try:
        return bytes(view.to_py())
    except Exception:
        length = int(view.length)
        return bytes(int(view[index]) for index in range(length))


def _binding(env: object, name: str) -> object | None:
    try:
        value = getattr(env, name)
    except Exception:
        return None
    if value is None:
        return None
    return value


async def _response_bytes(response: object) -> bytes:
    if hasattr(response, "bytes"):
        return bytes(await response.bytes())  # type: ignore[attr-defined]
    return buffer_to_bytes(await response.arrayBuffer())  # type: ignore[attr-defined]


async def _read_asset(assets: object, name: str) -> bytes:
    # ASSETS مثل یک fetch داخلی است و آدرس رشته‌ای می‌گیرد. دامنهٔ assets.local قراردادی است
    # و به اینترنت نمی‌رود؛ فقط نام فایل داخل پوشهٔ assets را مشخص می‌کند.
    response = await assets.fetch(f"https://assets.local/{name}")  # type: ignore[attr-defined]
    status = int(response.status)
    if status != 200:
        raise FileNotFoundError(f"asset {name} returned {status}")
    return await _response_bytes(response)


async def _read_r2(bucket: object, key: str) -> bytes:
    """شیء R2 را به بایت تبدیل می‌کند. بدنه گاهی روی خود شیء است و گاهی روی فیلد body."""
    obj = await bucket.get(key)  # type: ignore[attr-defined]
    if obj is None:
        raise FileNotFoundError(key)
    if hasattr(obj, "arrayBuffer"):
        return buffer_to_bytes(await obj.arrayBuffer())
    body = getattr(obj, "body", None)
    if body is not None and hasattr(body, "arrayBuffer"):
        return buffer_to_bytes(await body.arrayBuffer())
    raise FileNotFoundError(key)


async def load_sample_xlsx(env: object) -> bytes:
    """نمونه را از اولین منبع سالم می‌خواند. خطای R2 یا دارایی، تلاش بعدی را قطع نمی‌کند."""
    files = _binding(env, "FILES")
    if files is not None:
        try:
            data = await _read_r2(files, SAMPLE_NAME)
            if data:
                return data
        except Exception as exc:
            print("r2 sample.xlsx skipped:", type(exc).__name__)

    assets = _binding(env, "ASSETS")
    if assets is not None:
        try:
            data = await _read_asset(assets, SAMPLE_NAME)
            if data:
                return data
        except Exception as exc:
            print("asset sample.xlsx skipped:", type(exc).__name__, exc)

    return read_sample_from_disk()
