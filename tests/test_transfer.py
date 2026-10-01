"""قواعد کانال انتقال و تبدیل اکسل. شبکه و بله این‌جا نیستند."""

from io import BytesIO

import pytest
from openpyxl import Workbook

from excel_convert import ExcelConvertError, convert_excel_to_text, format_cell
from sheba import iban_check_digits
from transfer import (
    PAYA_MAX_RIAL,
    SATNA_MAX_RIAL,
    TransferValidationError,
    channel_for,
    parse_amount,
    parse_destination,
    parse_national_id,
    validate_single,
    with_national_check,
)


def sheba(bban: str) -> str:
    return f"IR{iban_check_digits('IR', bban)}{bban}"


MEHR = sheba("060" + "0" * 18 + "1")
OTHER = sheba("012" + "0" * 18 + "2")
NATIONAL = with_national_check("008457594")


def test_mehr_sheba_is_internal_even_inside_paya_and_satna_amounts():
    small, error = validate_single("علی رضایی", MEHR, "1500000")
    assert error is None and small is not None
    assert small.channel == "internal"
    assert small.account[4:7] == "060"

    large, error = validate_single("علی رضایی", MEHR, str(PAYA_MAX_RIAL + 1))
    assert error is None and large is not None
    assert large.channel == "internal"


def test_other_bank_sheba_splits_paya_and_satna_on_the_stated_bounds():
    at_paya, error = validate_single("سارا محمدی", OTHER, str(PAYA_MAX_RIAL))
    assert error is None and at_paya is not None
    assert at_paya.channel == "paya"

    above, error = validate_single("سارا محمدی", OTHER, str(PAYA_MAX_RIAL + 1))
    assert error is None and above is not None
    assert above.channel == "satna"

    at_satna, error = validate_single("سارا محمدی", OTHER, str(SATNA_MAX_RIAL))
    assert error is None and at_satna is not None
    assert at_satna.channel == "satna"

    above_ceiling, error = validate_single("سارا محمدی", OTHER, str(SATNA_MAX_RIAL + 1))
    assert error is None and above_ceiling is not None
    assert above_ceiling.channel == "satna"
    assert above_ceiling.needs_docs is True
    assert at_satna.needs_docs is False


def test_internal_account_is_not_treated_as_satna():
    row, error = validate_single("نرگس احمدی", "۱۲۳۴-۵۶۷۸-۹۰۱۲۳", str(PAYA_MAX_RIAL + 50))
    assert error is None and row is not None
    assert row.channel == "internal"
    assert row.account == "1234567890123"
    assert channel_for(parse_destination(row.account)[0], row.amount) == "internal"


@pytest.mark.parametrize(
    "raw",
    ["1234567", "1" * 16, "1" * 19, "1" * 24, "IR12", "not-an-account"],
)
def test_rejects_bad_destinations(raw: str):
    destination, error = parse_destination(raw)
    assert destination is None
    assert error


def test_bad_checksum_is_not_accepted_as_an_internal_account():
    broken = "IR" + "00" + "060" + "0" * 19
    destination, error = parse_destination(broken)
    assert destination is None
    assert error is not None
    assert "کنترلی" in error


def test_amount_accepts_persian_digits_and_rejects_zero_and_decimals():
    amount, error = parse_amount("۱٬۵۰۰٬۰۰۰ ریال")
    assert error is None and amount == 1_500_000
    assert parse_amount("0")[0] is None
    assert parse_amount("1500.5")[0] is None
    assert parse_amount("")[0] is None


def test_national_id_is_optional_but_checked_when_present():
    assert parse_national_id("") == ("", None)
    assert parse_national_id(NATIONAL) == (NATIONAL, None)
    code, error = parse_national_id("1234567890")
    assert code == "" and error is not None
    assert parse_national_id("0000000000")[1] is not None


def test_single_transfer_rejects_missing_name():
    row, error = validate_single("  ", OTHER, "1000")
    assert row is None and error is not None
    assert "نام" in error


def _xlsx(rows: list[list[object]], headers: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        headers
        or ["نام ذینفع", "کدملی", "شماره شبا / حساب ذینفع", "مبلغ", "شناسه واریز", "شرح"]
    )
    for row in rows:
        sheet.append(row)
    other = workbook.create_sheet("ignore-me")
    other.append(["SHOULD_NOT_APPEAR"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_excel_reports_channel_and_ignores_the_second_sheet():
    text = convert_excel_to_text(
        _xlsx(
            [
                ["علی رضایی", NATIONAL, MEHR, 1_500_000, "99", "حقوق"],
                ["سارا محمدی", None, OTHER, 250_000, None, None],
                ["رضا کریمی", None, OTHER, 2_500_000_000, None, "ساتنا"],
                ["نرگس احمدی", None, "1234567890123", 500_000, None, None],
            ]
        )
    )
    assert "SHOULD_NOT_APPEAR" not in text
    assert "نام ذینفع" in text.split("\n")[1]
    assert "داخلی" in text
    assert "پایا" in text
    assert "ساتنا" in text
    assert NATIONAL in text
    assert "سطر معتبر: 4" in text


def test_old_english_headers_still_map_but_output_is_the_new_report():
    text = convert_excel_to_text(
        _xlsx(
            [["علی رضایی", 1_500_000, OTHER]],
            headers=["name", "amount", "sheba"],
        )
    )
    assert text.split("\n")[0].startswith("سطر معتبر")
    assert "پایا" in text
    assert "name\tamount\tsheba" not in text


def test_invalid_row_is_a_persian_validation_error():
    with pytest.raises(TransferValidationError) as caught:
        convert_excel_to_text(_xlsx([["", None, "123", 0, None, None]]))
    message = caught.value.user_message
    assert "پذیرفته نشد" in message
    assert "مدیر" in message
    assert "سطر" in message


def test_missing_required_column_does_not_look_like_a_broken_file():
    with pytest.raises(TransferValidationError) as caught:
        convert_excel_to_text(_xlsx([["علی"]], headers=["نام ذینفع"]))
    assert "مبلغ" in caught.value.user_message
    assert "شماره شبا" in caught.value.user_message


def test_rejects_garbage_workbook():
    with pytest.raises(ExcelConvertError):
        convert_excel_to_text(b"this is not a zip")


def test_format_cell_integer_float_and_blank():
    assert format_cell(1500000.0) == "1500000"
    assert format_cell(None) == ""
    assert format_cell(False) == "false"


def test_truncation_note(monkeypatch):
    import excel_convert

    monkeypatch.setattr(excel_convert, "MAX_DATA_ROWS", 1)
    text = convert_excel_to_text(
        _xlsx(
            [
                ["علی رضایی", None, OTHER, 1000, None, None],
                ["سارا محمدی", None, OTHER, 2000, None, None],
            ]
        )
    )
    assert "سقف خروجی" in text
    assert "علی رضایی" in text
    assert "سارا محمدی" not in text
