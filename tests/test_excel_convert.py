"""خانه‌های اکسل و فایل ناخوانا. قواعد سطر و کانال در test_transfer است."""

from excel_convert import ExcelConvertError, convert_excel_to_text, format_cell


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
