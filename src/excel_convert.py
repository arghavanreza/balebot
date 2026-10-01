"""Excel (.xlsx) → text conversion.

TODO: نگاشت ستون‌ها هنوز نهایی نشده است و بعداً سفارشی می‌شود.
The default below is deliberate and temporary: the first worksheet is emitted
as tab-separated rows (header included), UTF-8, with no column renaming.
Replace `convert_excel_to_text` when the real mapping is decided. Callers
depend only on `bytes -> str`, so the rest of the bot can stay unchanged.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from io import BytesIO
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

# Safety caps so a hostile or accidental sheet cannot produce a huge upload.
MAX_ROWS = 5000
MAX_COLS = 50
_TRUNCATION_NOTE = "… سطرهای بعدی به‌خاطر سقف خروجی حذف شدند"


class ExcelConvertError(Exception):
    """The bytes were not a readable .xlsx workbook."""


def format_cell(value: object) -> str:
    """Render one cell as a single TSV field (no tabs or newlines)."""
    if value is None:
        return ""
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
    """Convert the first worksheet of an .xlsx file to tab-separated text.

    TODO: ستون‌ها (مثلاً name / amount / sheba) بعداً به قالب نهایی نگاشت می‌شوند.
    Until then, every non-empty row of the first sheet is written in order.
    Formula cells are exported as the formula text (`data_only=False`), because
    a file that has never been opened by Excel has no cached result.

    Other sheets are ignored. Completely empty rows are skipped.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ExcelConvertError("empty workbook")

    try:
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
