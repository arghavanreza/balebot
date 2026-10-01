"""تبدیل فایل اکسل (.xlsx) به متن.

TODO: نگاشت ستون‌ها هنوز نهایی نشده و بعداً سفارشی می‌شود.
رفتار فعلی عمداً موقت است: فقط شیت اول، هر سطر با تب، عنوان هم هست، خروجی UTF-8.
وقتی قالب واقعی معلوم شد فقط convert_excel_to_text را عوض کنید.
باقی بازو فقط «بایت داخل، رشته بیرون» را می‌شناسد و لازم نیست دست بخورد.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

# سقف امنیت: یک شیت خیلی بزرگ نباید فایل متنی غول‌پیکر برای مدیر بسازد.
MAX_ROWS = 5000
MAX_COLS = 50
_TRUNCATION_NOTE = "… سطرهای بعدی به‌خاطر سقف خروجی حذف شدند"


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


def convert_excel_to_text(data: bytes) -> str:
    """شیت اول را به متن جداشده با تب تبدیل می‌کند.

    TODO: ستون‌ها (مثلاً name / amount / sheba) بعداً به قالب نهایی نگاشت می‌شوند.
    تا آن موقع هر سطر غیرخالی شیت اول، به ترتیب، نوشته می‌شود.
    فرمول را به‌صورت خود متن فرمول می‌نویسیم نه نتیجهٔ محاسبه‌شده، چون فایلی که
    در اکسل باز نشده مقدار ذخیره‌شده ندارد.
    شیت‌های بعدی نادیده گرفته می‌شوند. سطر کاملاً خالی حذف می‌شود.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ExcelConvertError("empty workbook")

    try:
        # read_only حافظه را برای شیت بزرگ کمتر می‌خورد.
        # data_only=False یعنی فرمول را دست‌نخورده ببینیم، نه خانهٔ خالیِ بدون کش.
        workbook = load_workbook(
            BytesIO(bytes(data)),
            read_only=True,
            data_only=False,
        )
    except (InvalidFileException, BadZipFile, OSError, ValueError, KeyError, ET.ParseError) as exc:
        raise ExcelConvertError("unreadable xlsx") from exc

    lines: list[str] = []
    truncated = False
    try:
        if not workbook.worksheets:
            return ""
        sheet = workbook.worksheets[0]
        for row in sheet.iter_rows(values_only=True):
            cells = [format_cell(cell) for cell in row[:MAX_COLS]]
            if not any(cells):
                continue
            lines.append("\t".join(cells))
            if len(lines) >= MAX_ROWS:
                truncated = True
                break
    except (InvalidFileException, BadZipFile, OSError, ValueError, KeyError, ET.ParseError) as exc:
        raise ExcelConvertError("unreadable xlsx") from exc
    finally:
        workbook.close()

    if truncated:
        lines.append(_TRUNCATION_NOTE)
    return "\n".join(lines)
