"""تبدیل فایل اکسل انتقال وجه (.xlsx) به متن برای مدیر.

شیت اول خوانده می‌شود. ردیف عنوان باید ستون‌های نام ذینفع، شماره شبا یا حساب،
و مبلغ را داشته باشد. کدملی و شناسهٔ واریز و شرح اختیاری‌اند.
هر سطر داده با قواعد transfer.py سنجیده می‌شود و کانالش (داخلی، پایا، ساتنا)
در خروجی می‌آید. شیت‌های بعدی نادیده گرفته می‌شوند.

اگر فایل اصلاً اکسل نباشد ExcelConvertError می‌دهیم.
اگر اکسل باشد ولی سطرها از قاعده رد شوند TransferValidationError می‌دهیم
تا بازو آن را برای مدیر نفرستد.

فرمول را به‌صورت متن خود فرمول می‌بینیم نه نتیجهٔ محاسبه‌شده، چون فایلی که
در اکسل باز نشده مقدار ذخیره‌شده ندارد. چنین خانه‌ای معمولاً در اعتبارسنجی مبلغ رد می‌شود.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from transfer import TransferRow, collect_transfer_rows, format_transfer_table

# سقف امنیت: یک شیت خیلی بزرگ نباید فایل متنی غول‌پیکر برای مدیر بسازد.
# این عدد فقط سطر داده است. ردیف عنوان جدا شمرده می‌شود.
MAX_DATA_ROWS = 5000
MAX_COLS = 50

_UNREADABLE = (InvalidFileException, BadZipFile, OSError, ValueError, KeyError, ET.ParseError)


class ExcelConvertError(Exception):
    """بایت‌ها یک اکسل خوانا نبودند. بازو این خطا را به پیام فارسی برای فرستنده ترجمه می‌کند."""


def format_cell(value: object) -> str:
    """یک خانه را به یک فیلد متنی تبدیل می‌کند. تب و خط جدید داخل خانه حذف می‌شوند تا ستون‌ها نریزند."""
    if value is None:
        return ""
    # bool زیرکلاس int است. اگر این شاخه بعد از int باشد، true به «1» تبدیل می‌شود.
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, datetime):
        text = value.isoformat(sep=" ", timespec="seconds")
    elif isinstance(value, date):
        text = value.isoformat()
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        text = str(int(value)) if value.is_integer() else format(value, ".10g")
    else:
        text = str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def read_first_sheet(data: bytes) -> tuple[list[tuple[int, list[str]]], bool]:
    """سطرهای غیرخالی شیت اول را با شمارهٔ ردیف اکسل برمی‌گرداند.

    مقدار دوم True است اگر بعد از سقف، هنوز سطر داده مانده باشد.
    آن سطرها نه در خروجی می‌آیند و نه اعتبارسنجی می‌شوند.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ExcelConvertError("empty workbook")

    try:
        # read_only حافظه را برای شیت بزرگ کمتر می‌خورد.
        # data_only=False یعنی فرمول را دست‌نخورده ببینیم، نه خانهٔ خالیِ بدون کش.
        workbook = load_workbook(BytesIO(bytes(data)), read_only=True, data_only=False)
    except _UNREADABLE as exc:
        raise ExcelConvertError("unreadable xlsx") from exc

    collected: list[tuple[int, list[str]]] = []
    try:
        if not workbook.worksheets:
            return [], False
        sheet = workbook.worksheets[0]
        for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = [format_cell(cell) for cell in row[:MAX_COLS]]
            if not any(cells):
                continue
            collected.append((index, cells))
    except _UNREADABLE as exc:
        raise ExcelConvertError("unreadable xlsx") from exc
    finally:
        workbook.close()

    if not collected:
        return [], False
    header, data_rows = collected[0], collected[1:]
    truncated = len(data_rows) > MAX_DATA_ROWS
    kept = [header, *data_rows[:MAX_DATA_ROWS]]
    return kept, truncated


@dataclass(frozen=True)
class TransferBatch:
    """نتیجهٔ خواندن شیت اول. rows برای ساخت ccti است و text جدول کامل برای همراهی."""

    rows: list[TransferRow]
    text: str
    truncated: bool = False


def parse_workbook(data: bytes) -> TransferBatch:
    """اکسل را به سطرهای سنجیده‌شده تبدیل می‌کند.

    TransferValidationError را نمی‌گیریم تا گفتگو بین فایل خراب و سطر نامعتبر فرق بگذارد
    و دومی را برای مدیر نفرستد.
    """
    raw_rows, truncated = read_first_sheet(data)
    rows = collect_transfer_rows(raw_rows)
    return TransferBatch(
        rows=rows,
        text=format_transfer_table(rows, truncated=truncated),
        truncated=truncated,
    )


def convert_excel_to_text(data: bytes) -> str:
    """جدول متنی کامل. ساخت فایل پایا جداست و از خود سطرها می‌آید، نه از این متن."""
    return parse_workbook(data).text
