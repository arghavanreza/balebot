"""فایل پایا .ccti و این‌که فقط سطر پایا داخلش می‌رود."""

import xml.etree.ElementTree as ET
from io import BytesIO

from openpyxl import Workbook

from bot import handle_update
from ccti import (
    DEFAULT_DEBTOR_BIC,
    DEFAULT_DEBTOR_IBAN,
    DEFAULT_DEBTOR_NAME,
    build_ccti,
    gregorian_to_jalali,
    jalali_stamps,
    make_msg_id,
    mehr_debtor_iban,
    resolve_debtor,
)
from sheba import iban_check_digits
from test_bot import ADMIN, USER, FakeBale, _ctx, _document, _run, _text
from texts import DEFAULT_TEXTS
from transfer import TransferRow, format_channel_companion


def sheba(bban: str) -> str:
    return f"IR{iban_check_digits('IR', bban)}{bban}"


OTHER = sheba("012" + "0" * 18 + "2")
MEHR_OTHER_BRANCH = sheba("060" + "9" * 19)
PAYA = TransferRow(2, "علی رضایی", "", OTHER, 250_000, "", "بابت حقوق", "paya")
INTERNAL = TransferRow(3, "نرگس احمدی", "", "1234567890123", 3_000_000_000, "", "", "internal")
SATNA = TransferRow(4, "رضا کریمی", "0084575948", sheba("017" + "0" * 18 + "3"), 2_500_000_000, "99", "", "satna")


def test_jalali_matches_known_days_including_the_sample_date():
    # ۱۴۰۳-۰۷-۱۰ همان تاریخ داخل نمونهٔ ccti است (۱۰ مهر ۱۴۰۳ = ۱ اکتبر ۲۰۲۴).
    assert gregorian_to_jalali(2024, 10, 1) == (1403, 7, 10)
    assert gregorian_to_jalali(2024, 3, 20) == (1403, 1, 1)
    assert gregorian_to_jalali(2025, 3, 21) == (1404, 1, 1)
    created, day = jalali_stamps("2026-10-01T10:00:00Z")
    # ۱۰:۰۰ UTC یعنی ۱۳:۳۰ تهران.
    assert created == "1405-07-09T13:30:00"
    assert day == "1405-07-09"


def test_default_debtor_is_a_valid_mehr_sheba_and_branch_is_not_fixed():
    assert mehr_debtor_iban(DEFAULT_DEBTOR_IBAN) == DEFAULT_DEBTOR_IBAN
    assert mehr_debtor_iban(MEHR_OTHER_BRANCH) == MEHR_OTHER_BRANCH
    assert DEFAULT_DEBTOR_IBAN[4:7] == "060"
    assert MEHR_OTHER_BRANCH[4:7] == "060"
    try:
        mehr_debtor_iban(OTHER)
    except Exception as exc:
        assert "۰۶۰" in exc.user_message
    else:
        raise AssertionError("other bank sheba was accepted")


def test_ccti_contains_only_paya_rows_and_leaves_description_out():
    debtor = resolve_debtor(DEFAULT_TEXTS)
    assert debtor.name == DEFAULT_DEBTOR_NAME
    assert debtor.bic == DEFAULT_DEBTOR_BIC
    xml = build_ccti(
        [INTERNAL, PAYA, SATNA],
        debtor,
        now_iso="2026-10-01T10:00:00Z",
        nonce=7,
    )
    assert xml.startswith('<?xml version="1.0" encoding="utf-8" standalone="yes"?>')
    root = ET.fromstring(xml)
    assert root.tag == "Document"
    group = root.find("CstmrCdtTrfInitn/GrpHdr")
    assert group is not None
    assert group.findtext("NbOfTxs") == "1"
    assert group.findtext("CtrlSum") == "250000"
    assert group.findtext("CreDtTm") == "1405-07-09T13:30:00"
    message_id = group.findtext("MsgId")
    assert message_id == DEFAULT_DEBTOR_IBAN + "133000007"
    assert len(message_id) == 35
    payment = root.find("CstmrCdtTrfInitn/PmtInf")
    assert payment is not None
    method = payment.find("PmtMtd")
    assert method is not None
    assert method.text == "TRF"
    assert method.attrib["Ccy"] == "IRR"
    assert payment.findtext("ReqdExctnDt") == "1405-07-09"
    assert payment.findtext("DbtrAcct/Id/IBAN") == DEFAULT_DEBTOR_IBAN
    assert payment.findtext("DbtrAgt/FinInstnId/BIC") == "BMJIIRTHXXX"
    txs = payment.findall("CdtTrfTxInf")
    assert len(txs) == 1
    assert txs[0].findtext("Cdtr/Nm") == "علی رضایی"
    assert txs[0].findtext("Cdtr/Id/PrvtId/Othr/Id") == "EMPTY"
    assert txs[0].findtext("CdtrAcct/Id/IBAN") == OTHER
    assert txs[0].findtext("Amt/InstdAmt") == "250000"
    assert txs[0].find("Amt/InstdAmt").attrib["Ccy"] == "IRR"
    assert txs[0].findtext("PmtId/InstrId") == "EMPTY"
    assert txs[0].findtext("PmtId/EndToEndId") == "EMPTY"
    assert "1234567890123" not in xml
    assert "بابت حقوق" not in xml
    assert SATNA.account not in xml
    companion = format_channel_companion([INTERNAL, PAYA, SATNA], truncated=False)
    assert companion is not None
    assert "بابت حقوق" in companion
    assert "نرگس احمدی" in companion
    assert "ساتنا" in companion


def test_national_id_and_deposit_id_fill_the_empty_slots():
    row = TransferRow(2, "سارا & رضا", "0084575948", OTHER, 10, "555", "", "paya")
    xml = build_ccti(
        [row],
        resolve_debtor(DEFAULT_TEXTS),
        now_iso="2024-10-01T08:14:12Z",
        nonce=0,
    )
    tx = ET.fromstring(xml).find("CstmrCdtTrfInitn/PmtInf/CdtTrfTxInf")
    assert tx is not None
    assert tx.findtext("Cdtr/Nm") == "سارا & رضا"
    assert "&amp;" in xml
    assert tx.findtext("Cdtr/Id/PrvtId/Othr/Id") == "0084575948"
    assert tx.findtext("PmtId/InstrId") == "555"
    # ۰۸:۱۴ UTC = ۱۱:۴۴ تهران، همان ساعتی که شکل نمونه دارد، با تاریخ ۱۰ مهر ۱۴۰۳.
    assert "1403-07-10T11:44:12" in xml


def _xlsx(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["نام ذینفع", "شماره شبا / حساب ذینفع", "مبلغ", "شرح"])
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_mixed_upload_sends_ccti_for_paya_and_text_for_the_rest():
    async def scenario():
        payload = _xlsx(
            [
                ["علی رضایی", OTHER, 1500000, "شرح پایا"],
                ["نرگس احمدی", "1234567890123", 500000, None],
            ]
        )
        client = FakeBale(files={"file-1": payload})
        await handle_update(_document(USER, update_id=1), _ctx(client))
        names = [item["filename"] for item in client.documents]
        assert any(name.endswith(".ccti") for name in names)
        assert any(name.endswith(".txt") for name in names)
        xml = next(item["data"].decode() for item in client.documents if item["filename"].endswith(".ccti"))
        text = next(item["data"].decode() for item in client.documents if item["filename"].endswith(".txt"))
        assert OTHER in xml
        assert "1234567890123" not in xml
        assert "شرح پایا" not in xml
        assert "نرگس احمدی" in text
        assert "شرح پایا" in text
        assert all(str(item["chat_id"]) == ADMIN for item in client.documents)

    _run(scenario())


def test_non_mehr_debtor_blocks_the_paya_file():
    async def scenario():
        payload = _xlsx([["علی رضایی", OTHER, 1000, None]])
        client = FakeBale(files={"file-1": payload})
        ctx = _ctx(client)
        ctx.debtor_iban = OTHER
        await handle_update(_document(USER, update_id=1), ctx)
        assert client.documents == []
        assert "۰۶۰" in client.messages[-1]["text"]

    _run(scenario())


def test_internal_only_excel_does_not_build_ccti():
    async def scenario():
        payload = _xlsx([["نرگس احمدی", "1234567890123", 500000, None]])
        client = FakeBale(files={"file-1": payload})
        await handle_update(_document(USER, update_id=1), _ctx(client))
        assert len(client.documents) == 1
        assert client.documents[0]["filename"].endswith(".txt")
        assert b"CstmrCdtTrfInitn" not in client.documents[0]["data"]
        assert "داخلی" in client.documents[0]["data"].decode()

    _run(scenario())
