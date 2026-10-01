"""ثبت‌نام، سپردهٔ مهر، شکستن کانال، و فرم PDF.

شباها با رقم کنترل ساخته می‌شوند و حساب واقعی نیستند. شبکه و توکن این‌جا نیست.
"""

from io import BytesIO

from openpyxl import Workbook

from bot import handle_update
from deposits import parse_deposit_callback
from national_id import national_id_check_digit, normalize_national_id, parse_full_name
from pdf_declaration import build_declaration_pdf, declaration_lines, read_font_from_disk
from sheba import iban_check_digits, is_mehr_sheba
from test_bot import ADMIN, USER, FakeBale, _ctx, _document, _run, _text
from texts import DEFAULT_TEXTS
from transfer import SATNA_MAX_RIAL, any_needs_docs, validate_single
from users import (
    INSERT_DEPOSIT_SQL,
    SET_FULL_NAME_SQL,
    SET_NATIONAL_ID_SQL,
    D1UserStore,
    MemoryUserStore,
)


def _sheba(bank: str) -> str:
    bban = bank + "0" * 19
    return f"IR{iban_check_digits('IR', bban)}{bban}"


MEHR = _sheba("060")
OTHER = _sheba("012")
VALID_NID = "1234567891"


def test_national_id_checksum_and_name():
    assert national_id_check_digit("123456789") == "1"
    assert normalize_national_id("۱۲۳۴۵۶۷۸۹۱") == VALID_NID
    assert normalize_national_id("12345-67891") == VALID_NID
    assert normalize_national_id("1111111111") is None
    assert normalize_national_id("1234567890") is None
    assert normalize_national_id("IR1234567891") is None
    assert parse_full_name("  علی   رضایی ") == "علی رضایی"
    assert parse_full_name("علی") is None
    assert parse_full_name("علی 123") is None


def test_mehr_sheba_accepts_any_branch():
    other_branch = "060" + "12345" + "0" * 14
    branched = f"IR{iban_check_digits('IR', other_branch)}{other_branch}"
    assert is_mehr_sheba(MEHR)
    assert is_mehr_sheba(branched)
    assert not is_mehr_sheba(OTHER)


def test_amount_above_five_billion_stays_satna_and_asks_for_documents():
    row, error = validate_single("سارا محمدی", OTHER, str(SATNA_MAX_RIAL + 1))
    assert error is None and row is not None
    assert row.channel == "satna"
    assert row.needs_docs is True
    assert any_needs_docs([row]) is True
    internal, error = validate_single("علی رضایی", MEHR, str(SATNA_MAX_RIAL + 1))
    assert error is None and internal is not None
    assert internal.channel == "internal"
    assert internal.needs_docs is False


def test_declaration_pdf_contains_the_sentence_and_rows():
    lines = declaration_lines(
        "علی رضایی",
        VALID_NID,
        {"paya": [{"name": "سارا", "amount": 10, "account": OTHER}]},
    )
    assert any(VALID_NID in line and "علی رضایی" in line for line in lines)
    assert any("سارا" in line for line in lines)
    pdf = build_declaration_pdf(lines, read_font_from_disk())
    assert pdf.startswith(b"%PDF")
    assert b"%%EOF" in pdf
    assert VALID_NID.encode("utf-16-be").hex().encode("ascii") in pdf


def _payroll(rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["نام ذینفع", "شماره شبا / حساب ذینفع", "مبلغ"])
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _callback(data: str, update_id: int) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cq-{update_id}",
            "from": {"id": int(USER), "first_name": "علی"},
            "data": data,
            "message": {"message_id": 1, "chat": {"id": int(USER)}},
        },
    }


async def _register(client: FakeBale, ctx, start: int = 1) -> None:
    await handle_update(_text(USER, "/start", update_id=start), ctx)
    await handle_update(_text(USER, "09121234567", update_id=start + 1), ctx)
    await handle_update(_text(USER, "علی رضایی", update_id=start + 2), ctx)
    await handle_update(_text(USER, VALID_NID, update_id=start + 3), ctx)


def test_admin_skips_registration_and_customer_must_finish_it():
    async def scenario():
        client = FakeBale()
        ctx = _ctx(client)
        ctx.users = MemoryUserStore()
        await handle_update(_text(ADMIN, "/start", update_id=1), ctx)
        admin_labels = [
            button
            for row in client.messages[-1]["reply_markup"]["keyboard"]
            for button in row
        ]
        assert DEFAULT_TEXTS["btn_edit"] in admin_labels
        assert DEFAULT_TEXTS["btn_deposits"] in admin_labels
        await _register(client, ctx, start=2)
        profile = await ctx.users.get(int(USER))
        assert profile is not None
        assert profile.full_name == "علی رضایی"
        assert profile.national_id == VALID_NID
        labels = [
            button
            for row in client.messages[-1]["reply_markup"]["keyboard"]
            for button in row
        ]
        assert DEFAULT_TEXTS["btn_deposits"] in labels
        assert DEFAULT_TEXTS["btn_group"] in labels

    _run(scenario())


def test_group_upload_sends_separate_ccti_files_profile_and_pdf():
    async def scenario():
        payload = _payroll(
            [
                ["نرگس احمدی", "1234567890123", 500000],
                ["سارا محمدی", OTHER, 1500000],
                ["رضا کریمی", OTHER, SATNA_MAX_RIAL + 50],
            ]
        )
        client = FakeBale(files={"file-1": payload})
        ctx = _ctx(client)
        ctx.users = MemoryUserStore()
        ctx.clock = lambda: "2026-10-01T10:00:00Z"
        await _register(client, ctx)
        await handle_update(_text(USER, DEFAULT_TEXTS["btn_deposits"], update_id=10), ctx)
        add = client.messages[-1]["reply_markup"]["inline_keyboard"][-1][0]
        assert parse_deposit_callback(add["callback_data"]) == ("add", None)
        await handle_update(_callback(add["callback_data"], 11), ctx)
        await handle_update(_text(USER, OTHER, update_id=12), ctx)
        assert "۰۶۰" in client.messages[-1]["text"]
        await handle_update(_text(USER, MEHR + "\nحقوق", update_id=13), ctx)
        active = await ctx.users.list_deposits(int(USER))
        assert len(active) == 1 and active[0].is_active and active[0].label == "حقوق"

        await handle_update(_document(USER, update_id=14), ctx)
        names = [item["filename"] for item in client.documents if str(item["chat_id"]) == ADMIN]
        assert "dakheli.ccti" in names
        assert "paya.ccti" in names
        assert "satna.ccti" in names
        paya = next(item for item in client.documents if item["filename"] == "paya.ccti")
        internal = next(item for item in client.documents if item["filename"] == "dakheli.ccti")
        assert OTHER in paya["data"].decode()
        assert "1234567890123" not in paya["data"].decode()
        assert b"1234567890123" in internal["data"]
        assert MEHR in paya["data"].decode()
        admin_text = "\n".join(message["text"] for message in client.messages if str(message["chat_id"]) == ADMIN)
        assert "+989121234567" in admin_text
        assert "علی رضایی" in admin_text
        assert VALID_NID in admin_text
        assert MEHR in admin_text
        pdfs = [item for item in client.documents if item["filename"] == "declaration.pdf"]
        assert {str(item["chat_id"]) for item in pdfs} == {ADMIN, USER}
        assert any("چاپ" in message["text"] for message in client.messages if str(message["chat_id"]) == USER)
        assert (await ctx.states.get(USER)).get("flow") == "transfer_docs"

        client.files["photo-1"] = b"jpeg-bytes"
        photo = _text(USER, "", update_id=15)
        photo["message"].pop("text")
        photo["message"]["photo"] = [{"file_id": "photo-1", "file_size": 10}]
        await handle_update(photo, ctx)
        forwarded = [item for item in client.documents if item["filename"] == "support.jpg"]
        assert forwarded and str(forwarded[-1]["chat_id"]) == ADMIN
        assert b"jpeg-bytes" in forwarded[-1]["data"]

    _run(scenario())


def test_d1_profile_and_deposit_statements_are_bound():
    async def scenario():
        class _Stmt:
            def __init__(self, log, sql, rows):
                self.log = log
                self.sql = sql
                self.params = ()
                self._rows = rows

            def bind(self, *params):
                self.params = params
                return self

            async def run(self):
                self.log.append(("run", self.sql, self.params))
                return {"success": True}

            async def all(self):
                self.log.append(("all", self.sql, self.params))
                from users import LIST_DEPOSITS_SQL, SELECT_DEPOSIT_SQL

                if self.sql == SELECT_DEPOSIT_SQL:
                    return {"success": True, "results": list(self._rows)}
                if self.sql == LIST_DEPOSITS_SQL:
                    return {"success": True, "results": []}
                return {"success": True, "results": []}

        class _DB:
            def __init__(self):
                self.log = []
                self.rows = [
                    {
                        "id": 4,
                        "user_id": 7,
                        "sheba": MEHR,
                        "label": "حقوق",
                        "is_active": 1,
                        "created_at": "2026-10-01T10:00:00Z",
                    }
                ]

            def prepare(self, sql):
                return _Stmt(self.log, sql, self.rows)

        from users import UserProfile

        db = _DB()
        store = D1UserStore(db)
        await store.touch(
            UserProfile(
                user_id=7,
                username=None,
                first_name="علی",
                last_name=None,
                language_code="fa",
                is_admin=False,
                first_seen_at="2026-10-01T10:00:00Z",
                last_seen_at="2026-10-01T10:00:00Z",
                message_count=0,
            )
        )
        assert await store.set_full_name(7, "علی رضایی") is True
        assert await store.set_national_id(7, VALID_NID) is True
        assert ("run", SET_FULL_NAME_SQL, ("علی رضایی", 7)) in db.log
        assert ("run", SET_NATIONAL_ID_SQL, (VALID_NID, 7)) in db.log
        created = await store.add_deposit(7, MEHR, "حقوق", "2026-10-01T10:00:00Z")
        assert created is not None
        assert created.is_active is True
        assert any(kind == "run" and sql == INSERT_DEPOSIT_SQL for kind, sql, _params in db.log)

    _run(scenario())
