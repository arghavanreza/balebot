from datetime import datetime
from io import BytesIO

from openpyxl import Workbook

from excel_convert import ExcelConvertError, convert_excel_to_text, format_cell


def _workbook_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "payments"
    sheet.append(["name", "amount", "sheba"])
    sheet.append(["علی رضایی", 1500000, "IR430120000000000000000001"])
    sheet.append([None, None, None])
    sheet.append(["سارا", 250000.5, "a\tb\nc"])
    sheet["A5"] = datetime(2026, 10, 1, 8, 30, 0)
    sheet["B5"] = True
    other = workbook.create_sheet("ignore-me")
    other.append(["secret", "SHOULD_NOT_APPEAR"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_default_converter_is_tsv_from_the_first_sheet():
    text = convert_excel_to_text(_workbook_bytes())
    lines = text.split("\n")
    assert lines[0] == "name\tamount\tsheba"
    assert lines[1] == "علی رضایی\t1500000\tIR430120000000000000000001"
    assert lines[2] == "سارا\t250000.5\ta b c"
    assert lines[3].startswith("2026-10-01 08:30:00\ttrue")
    assert "SHOULD_NOT_APPEAR" not in text


def test_format_cell_integer_float_and_blank():
    assert format_cell(1500000.0) == "1500000"
    assert format_cell(None) == ""
    assert format_cell(False) == "false"


def test_rejects_garbage():
    try:
        convert_excel_to_text(b"this is not a zip")
    except ExcelConvertError:
        return
    raise AssertionError("expected ExcelConvertError")


def test_truncation_note(monkeypatch):
    import excel_convert

    monkeypatch.setattr(excel_convert, "MAX_ROWS", 1)
    text = convert_excel_to_text(_workbook_bytes())
    assert text.split("\n")[0] == "name\tamount\tsheba"
    assert "سقف خروجی" in text
    assert "علی" not in text
