"""فایل پایا با الگوی CstmrCdtTrfInitn (نمونهٔ .ccti بانک).

فقط سطرهایی که کانالشان پایا است داخل این XML می‌روند. داخلی و ساتنا متن می‌مانند.
شرح در این الگو فیلد ندارد. گذاشتنش در یک برچسب اضافه ممکن است واردکنندهٔ بانک را رد کند،
برای همین شرح در متن همراه مدیر می‌ماند نه در خود فایل.

تاریخ نمونه شمسی است (مثل ۱۴۰۳-۰۷-۱۰) نه میلادی. ساعت را به وقت تهران حساب می‌کنیم
و بعد به جلالی تبدیل می‌کنیم، چون شعبه همین تقویم را در فایل انتظار دارد.
از zoneinfo استفاده نمی‌کنیم؛ اختلاف تهران با UTC همیشه ۳:۳۰ است.

شبای مبدأ باید شبا معتبر بانک مهر باشد، یعنی کد بانک ۰۶۰.
شعبهٔ داخل شماره مهم نیست: هر شبای ۰۶۰ معتبر برای پایا کافی است.
مقدار پیش‌فرض همان شبای نمونه است و موقتی است تا مدیر از منوی متن یا متغیر محیط عوضش کند.
"""

from __future__ import annotations

from dataclasses import dataclass

from sheba import validate_sheba
from stats import TEHRAN, parse_utc_iso
from transfer import TransferRow

# موقت، از فایل نمونهٔ بانک. مدیر باید با کلید متن یا DEBTOR_* عوضشان کند.
# شعبهٔ خاصی در این پیش‌فرض قفل نیست؛ فقط شبا معتبر و کد ۰۶۰ لازم است.
DEFAULT_DEBTOR_NAME = "طراني ملا*محمد*ناصر"
DEFAULT_DEBTOR_IBAN = "IR480600403679704083284001"
DEFAULT_DEBTOR_BIC = "BMJIIRTHXXX"

MEHR_BANK_CODE = "060"
_EMPTY = "EMPTY"


class CctiConfigError(Exception):
    """حساب مبدأ پایا قابل استفاده در فایل بانک نیست. user_message برای مشتری و مدیر است."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class Debtor:
    """صاحب حساب مبدأ. iban نرمال‌شده و حتماً کد ۰۶۰ است."""

    name: str
    iban: str
    bic: str


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """تاریخ میلادی را به شمسی برمی‌گرداند. الگوریتم رایج ۳۳ساله، بدون جدول خارجی."""
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_days[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + (days % 31)
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def jalali_stamps(now_iso: str) -> tuple[str, str]:
    """(CreDtTm, ReqdExctnDt) مثل نمونه: ۱۴۰۳-۰۷-۱۰T۱۱:۴۴:۱۲ و ۱۴۰۳-۰۷-۱۰.

    رقم‌ها لاتین می‌مانند چون خود نمونه همین شکل را دارد و بانک عدد لاتین می‌خواند.
    """
    local = parse_utc_iso(now_iso).astimezone(TEHRAN)
    jy, jm, jd = gregorian_to_jalali(local.year, local.month, local.day)
    created = f"{jy:04d}-{jm:02d}-{jd:02d}T{local.hour:02d}:{local.minute:02d}:{local.second:02d}"
    return created, created[:10]


def make_msg_id(iban: str, now_iso: str, nonce: int) -> str:
    """شناسهٔ پیام ۳۵ نویسه‌ای: شبای مبدأ (۲۶) به‌اضافهٔ ۹ رقم، مثل نمونه.

    ۶ رقم ساعت تهران است (HHMMSS) و ۳ رقم باقی‌ماندهٔ شناسهٔ فرستنده بر ۱۰۰۰
    تا دو مشتری در یک ثانیه شناسهٔ یکی نسازند. شعبه در این شناسه نقشی ندارد.
    """
    local = parse_utc_iso(now_iso).astimezone(TEHRAN)
    suffix = f"{local.hour:02d}{local.minute:02d}{local.second:02d}{nonce % 1000:03d}"
    return iban + suffix


def mehr_debtor_iban(raw: str) -> str:
    """شبا را نرمال می‌کند. باید معتبر باشد و کد بانکش ۰۶۰ باشد.

    رقم‌های بعد از کد بانک (شعبه و سریال حساب) بررسی نمی‌شوند.
    شبای بانک دیگر، حتی با رقم کنترل درست، برای مبدأ پایا این بازو قبول نیست.
    """
    check = validate_sheba(raw)
    if not check.valid:
        raise CctiConfigError(
            "شبای مبدأ پایا معتبر نیست. باید با IR و رقم کنترل درست باشد."
        )
    bank = check.normalized[4:7]
    if bank != MEHR_BANK_CODE:
        raise CctiConfigError(
            "شبای مبدأ پایا باید شبا بانک مهر باشد (کد ۰۶۰). شعبهٔ خاصی لازم نیست."
        )
    return check.normalized


def resolve_debtor(
    texts: dict[str, str],
    *,
    name: str = "",
    iban: str = "",
    bic: str = "",
) -> Debtor:
    """نام و شبا و BIC را از محیط، وگرنه از متن قابل‌ویرایش، وگرنه از پیش‌فرض نمونه برمی‌دارد."""
    chosen_name = (name or texts.get("debtor_name") or DEFAULT_DEBTOR_NAME).strip()
    chosen_iban = (iban or texts.get("debtor_iban") or DEFAULT_DEBTOR_IBAN).strip()
    chosen_bic = (bic or texts.get("debtor_bic") or DEFAULT_DEBTOR_BIC).strip().upper()
    if not chosen_name:
        raise CctiConfigError("نام صاحب حساب مبدأ پایا خالی است.")
    if len(chosen_name) > 140:
        raise CctiConfigError("نام صاحب حساب مبدأ پایا طولانی است.")
    if not chosen_bic.isalnum() or len(chosen_bic) not in {8, 11}:
        raise CctiConfigError("BIC مبدأ پایا باید ۸ یا ۱۱ نویسهٔ حرف و رقم باشد.")
    return Debtor(name=chosen_name, iban=mehr_debtor_iban(chosen_iban), bic=chosen_bic)


def xml_text(value: str) -> str:
    """نویسه‌هایی که XML را می‌شکنند عوض می‌شوند. ستارهٔ نام نمونه دست نمی‌خورد."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _or_empty(value: str) -> str:
    text = value.strip()
    return text if text else _EMPTY


def _transaction(row: TransferRow) -> str:
    # شناسهٔ واریز در هر دو شناسهٔ دستور می‌نشیند. شرح عمداً این‌جا نیست.
    payment_id = xml_text(_or_empty(row.deposit_id))
    national_id = xml_text(_or_empty(row.national_id))
    return "\n".join(
        [
            "\t\t\t<CdtTrfTxInf>",
            "\t\t\t\t<PmtId>",
            f"\t\t\t\t\t<InstrId>{payment_id}</InstrId>",
            f"\t\t\t\t\t<EndToEndId>{payment_id}</EndToEndId>",
            "\t\t\t\t</PmtId>",
            "\t\t\t\t<Amt>",
            f'\t\t\t\t\t<InstdAmt Ccy="IRR">{row.amount}</InstdAmt>',
            "\t\t\t\t</Amt>",
            "\t\t\t\t<Cdtr>",
            f"\t\t\t\t\t<Nm>{xml_text(row.name)}</Nm>",
            "\t\t\t\t\t<Id>",
            "\t\t\t\t\t\t<PrvtId>",
            "\t\t\t\t\t\t\t<Othr>",
            f"\t\t\t\t\t\t\t\t<Id>{national_id}</Id>",
            "\t\t\t\t\t\t\t</Othr>",
            "\t\t\t\t\t\t</PrvtId>",
            "\t\t\t\t\t</Id>",
            "\t\t\t\t</Cdtr>",
            "\t\t\t\t<CdtrAcct>",
            "\t\t\t\t\t<Id>",
            f"\t\t\t\t\t\t<IBAN>{xml_text(row.account)}</IBAN>",
            "\t\t\t\t\t</Id>",
            "\t\t\t\t</CdtrAcct>",
            "\t\t\t</CdtTrfTxInf>",
        ]
    )


def build_ccti(
    rows: list[TransferRow],
    debtor: Debtor,
    *,
    now_iso: str,
    nonce: int,
) -> str:
    """XML پایا را می‌سازد. سطر غیرپایا را نادیده می‌گیرد.

    اگر بعد از این صافی چیزی نماند خطا می‌دهیم تا فایل خالی به بانک نرود.
    """
    paya = [row for row in rows if row.channel == "paya"]
    if not paya:
        raise CctiConfigError("سطر پایا برای ساخت فایل ccti نیست.")
    count = len(paya)
    total = sum(row.amount for row in paya)
    created, execution = jalali_stamps(now_iso)
    message_id = make_msg_id(debtor.iban, now_iso, nonce)
    name = xml_text(debtor.name)
    transactions = "\n".join(_transaction(row) for row in paya)
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n'
        "<Document>\n"
        "\t<CstmrCdtTrfInitn>\n"
        "\t\t<GrpHdr>\n"
        f"\t\t\t<MsgId>{message_id}</MsgId>\n"
        f"\t\t\t<CreDtTm>{created}</CreDtTm>\n"
        f"\t\t\t<NbOfTxs>{count}</NbOfTxs>\n"
        f"\t\t\t<CtrlSum>{total}</CtrlSum>\n"
        "\t\t\t<InitgPty>\n"
        f"\t\t\t\t<Nm>{name}</Nm>\n"
        "\t\t\t</InitgPty>\n"
        "\t\t</GrpHdr>\n"
        "\t\t<PmtInf>\n"
        "\t\t\t<PmtInfId>1</PmtInfId>\n"
        '\t\t\t<PmtMtd Ccy="IRR">TRF</PmtMtd>\n'
        f"\t\t\t<NbOfTxs>{count}</NbOfTxs>\n"
        f"\t\t\t<CtrlSum>{total}</CtrlSum>\n"
        f"\t\t\t<ReqdExctnDt>{execution}</ReqdExctnDt>\n"
        "\t\t\t<Dbtr>\n"
        f"\t\t\t\t<Nm>{name}</Nm>\n"
        "\t\t\t</Dbtr>\n"
        "\t\t\t<DbtrAcct>\n"
        "\t\t\t\t<Id>\n"
        f"\t\t\t\t\t<IBAN>{debtor.iban}</IBAN>\n"
        "\t\t\t\t</Id>\n"
        "\t\t\t</DbtrAcct>\n"
        "\t\t\t<DbtrAgt>\n"
        "\t\t\t\t<FinInstnId>\n"
        f"\t\t\t\t\t<BIC>{debtor.bic}</BIC>\n"
        "\t\t\t\t</FinInstnId>\n"
        "\t\t\t</DbtrAgt>\n"
        f"{transactions}\n"
        "\t\t</PmtInf>\n"
        "\t</CstmrCdtTrfInitn>\n"
        "</Document>\n"
    )
