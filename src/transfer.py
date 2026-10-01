"""قواعد انتقال وجه و خواندن جدول اکسل.

سه کانال از روی مقصد و مبلغ تعیین می‌شود، نه از روی انتخاب مشتری:

- داخلی: شبای بانک قرض‌الحسنه مهر ایران، یا شماره حساب همین بانک.
  کد بانک در شبا ۰۶۰ است. شکل شبا: IR و دو رقم کنترلی و بعد ۰۶۰.
  یعنی از بخش عددی بعد از IR، رقم‌های سوم تا پنجم برابر ۰۶۰ هستند.
  مثال: IRxx060… انتقال داخلی است حتی اگر مبلغ در بازهٔ پایا یا ساتنا باشد.
- پایا: شبای بانک دیگر، مبلغ از ۱ ریال تا ۲٬۰۰۰٬۰۰۰٬۰۰۰ ریال (شامل خود سقف).
- ساتنا: شبای بانک دیگر، مبلغ بیشتر از ۲ میلیارد.
  تا ۵٬۰۰۰٬۰۰۰٬۰۰۰ ریال (شامل) ساتنای عادی است.
  بیشتر از ۵ میلیارد همچنان ساتنا است، ولی needs_docs روی همان سطر روشن می‌شود
  تا بازو از مشتری عکس یا PDF مدارک را بخواهد. پردازش قطع نمی‌شود.

شماره کارت ۱۶ رقمی حساب نیست.
شناسهٔ واریز اختیاری است؛ این نسخه برای هیچ کانالی اجباری‌اش نمی‌کند،
ولی اگر پر شده باشد باید فقط رقم باشد.

خروجی این ماژول متن است. فرستادن به مدیر کار bot.py است و ایمیلی در کار نیست.
"""

from __future__ import annotations

from dataclasses import dataclass

from sheba import validate_sheba

# ارقام فارسی و عربی را به لاتین برمی‌گردانیم تا «۱۰۰۰» و «1000» یکی شوند.
_DIGIT_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LATIN_TO_PERSIAN = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
# ی و ک عربی و نیم‌فاصله را یکدست می‌کنیم تا عنوان ستون با کیبورد عربی هم جور شود.
_LETTER_FOLD = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": "", "\u200d": ""})

# کد سه رقمی بانک مهر داخل شبا. جایگاهش پایین‌تر، کنار channel_for، توضیح داده شده است.
MEHR_BANK_CODE = "060"
PAYA_MAX_RIAL = 2_000_000_000
SATNA_MAX_RIAL = 5_000_000_000

# شماره حساب داخلی مهر: فقط رقم، بین ۸ و ۱۸ رقم.
# کمتر از ۸ رقم معمولاً کد شعبه یا مبلغِ جاافتاده در ستون حساب است.
# شبا بدون IR بیست‌وچهار رقم است؛ سقف ۱۸ نمی‌گذارد آن عدد حساب داخلی شود.
# شبا باید با IR بیاید تا رقم کنترلی‌اش سنجیده شود.
# ۱۶ رقم را جدا رد می‌کنیم چون شماره کارت بانکی ایران ۱۶ رقم است، نه حساب سپرده.
ACCOUNT_MIN_DIGITS = 8
ACCOUNT_MAX_DIGITS = 18
CARD_DIGITS = 16

MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 120
MAX_DEPOSIT_ID_LENGTH = 30
# بیشتر از این رقم را اصلاً به int نمی‌دهیم؛ سقف واقعی ۵ میلیارد است و ۱۰ رقم دارد.
_MAX_AMOUNT_DIGITS = 18
_MAX_ERROR_LINES = 12

CHANNEL_LABELS = {
    "internal": "داخلی",
    "paya": "پایا",
    "satna": "ساتنا",
}

# عنوان ستون در فایل نمونه و در خروجی مدیر. کلید داخلی برای کد است، برچسب برای انسان.
FIELD_LABELS = {
    "name": "نام ذینفع",
    "national_id": "کدملی",
    "account": "شماره شبا / حساب ذینفع",
    "amount": "مبلغ",
    "deposit_id": "شناسه واریز",
    "description": "شرح",
}

# عنوان‌هایی که بعد از یکدست‌سازی دقیقاً با این‌ها برابرند پذیرفته می‌شوند.
# نام انگلیسی ستون‌های نمونهٔ قبلی هم این‌جاست تا فایلی که هنوز name/amount/sheba دارد
# از نظر ستون گم نشود؛ خروجی ولی دیگر همان سه ستون خام نیست و کانال هم دارد.
_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("نامذینفع", "نام", "name", "beneficiary"),
    "national_id": ("کدملی", "nationalid", "nationalcode"),
    "account": (
        "شمارهشباحسابذینفع",
        "شمارهشبا",
        "حسابذینفع",
        "شبا",
        "حساب",
        "sheba",
        "iban",
        "account",
    ),
    "amount": ("مبلغ", "مبلغریال", "مبلغبهریال", "amount"),
    "deposit_id": ("شناسهواریز", "شناسه", "depositid", "paymentid"),
    "description": ("شرح", "توضیحات", "بابت", "description"),
}

_REQUIRED_FIELDS = ("name", "account", "amount")

OUTPUT_COLUMNS = (
    "ردیف",
    "نام ذینفع",
    "کدملی",
    "شماره شبا / حساب ذینفع",
    "مبلغ",
    "شناسه واریز",
    "شرح",
    "کانال",
)

_TRUNCATION_NOTE = "… سطرهای بعدی به‌خاطر سقف خروجی حذف شدند و بررسی نشدند"


class TransferValidationError(Exception):
    """فایل اکسل خوانا بود ولی قاعدهٔ انتقال را رد کرد.

    user_message همان متن فارسی برای مشتری است. این خطا را به مدیر نمی‌فرستیم.
    """

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class Destination:
    """مقصد نرمال‌شده.

    kind برابر sheba یا account است. bank_code فقط برای شبا پر است
    و برای تشخیص ۰۶۰ به کار می‌رود. شماره حساب داخلی خودش بانک مهر است
    و کد جدا ندارد.
    """

    kind: str
    normalized: str
    bank_code: str | None


@dataclass(frozen=True)
class TransferRow:
    """یک انتقال که هم نام و مبلغش معتبر است و هم کانالش مشخص شده."""

    excel_row: int
    name: str
    national_id: str
    account: str
    amount: int
    deposit_id: str
    description: str
    channel: str

    @property
    def channel_label(self) -> str:
        return CHANNEL_LABELS[self.channel]

    @property
    def needs_docs(self) -> bool:
        """غیرمهر و بیشتر از سقف اسمی ساتنا. فایل ساتنا ساخته می‌شود و مدارک جدا خواسته می‌شود."""
        return self.channel == "satna" and self.amount > SATNA_MAX_RIAL


def format_rial(amount: int) -> str:
    """مبلغ را با جداکنندهٔ هزارگان و رقم فارسی نشان می‌دهد، فقط برای جملهٔ خطا."""
    return f"{amount:,}".translate(_LATIN_TO_PERSIAN)


def fold_header(value: str) -> str:
    """عنوان ستون را برای مقایسه ساده می‌کند: فاصله، اسلش، ی/ک و کوچکی لاتین."""
    text = value.translate(_LETTER_FOLD).translate(_DIGIT_FOLD).lower()
    drop = set(" \t/\\()_-–—:：،,.ـ")
    return "".join(char for char in text if char not in drop)


def with_national_check(first9: str) -> str:
    """رقم دهم کدملی را می‌سازد. فقط برای نمونه و تست است، نه برای ورودی مشتری."""
    if len(first9) != 9 or not first9.isdigit():
        raise ValueError("national id base must be 9 digits")
    return first9 + _national_check_digit(first9)


def _national_check_digit(first9: str) -> str:
    # وزن رقم اول ۱۰ است و رقم نهم ۲. باقی‌ماندهٔ ۱۱ اگر کمتر از ۲ باشد خودش رقم کنترل است.
    total = sum(int(first9[index]) * (10 - index) for index in range(9))
    remainder = total % 11
    check = remainder if remainder < 2 else 11 - remainder
    return str(check)


def _national_checksum_ok(code: str) -> bool:
    return _national_check_digit(code[:9]) == code[9]


def validate_beneficiary_name(name: str) -> str | None:
    """نام خالی یا فقط‌عدد را رد می‌کند. None یعنی همین نام قابل ذخیره است."""
    cleaned = " ".join(name.split())
    if len(cleaned) < 2:
        return "نام ذینفع را کامل بنویسید."
    if len(cleaned) > MAX_NAME_LENGTH:
        return f"نام ذینفع طولانی است. حداکثر {MAX_NAME_LENGTH} نویسه."
    compact = "".join(char for char in cleaned.translate(_DIGIT_FOLD) if char.isalnum())
    if compact.isdigit():
        return "نام ذینفع نمی‌تواند فقط عدد باشد."
    return None


def parse_national_id(value: str) -> tuple[str, str | None]:
    """کدملی خالی مجاز است. اگر پر باشد باید ۱۰ رقم با رقم کنترل درست باشد.

    کدهایی که هر ده رقمشان یکی است (مثل ۰۰۰…۰) از نظر فرمول گاهی قبول می‌شوند
    ولی ثبت‌احوال چنین شماره‌ای نمی‌دهد، برای همین جدا رد می‌شوند.
    """
    raw = value.translate(_DIGIT_FOLD)
    raw = "".join(char for char in raw if char not in " \t-\u200c")
    if not raw:
        return "", None
    if not raw.isdigit() or len(raw) != 10:
        return "", "کدملی باید ۱۰ رقم باشد."
    if len(set(raw)) == 1 or not _national_checksum_ok(raw):
        return "", "کدملی نامعتبر است."
    return raw, None


def parse_deposit_id(value: str) -> tuple[str, str | None]:
    """شناسهٔ واریز اختیاری است. خالی قبول است و مقدار غیررقمی رد می‌شود."""
    text = "".join(value.translate(_DIGIT_FOLD).split())
    if not text:
        return "", None
    if not text.isdigit():
        return "", "شناسه واریز باید فقط رقم باشد."
    if len(text) > MAX_DEPOSIT_ID_LENGTH:
        return "", f"شناسه واریز طولانی است. حداکثر {MAX_DEPOSIT_ID_LENGTH} رقم."
    return text, None


def parse_description(value: str) -> tuple[str, str | None]:
    text = " ".join(value.split())
    if not text:
        return "", None
    if len(text) > MAX_DESCRIPTION_LENGTH:
        return "", f"شرح طولانی است. حداکثر {MAX_DESCRIPTION_LENGTH} نویسه."
    return text, None


def parse_amount(raw: str) -> tuple[int | None, str | None]:
    """مبلغ ریالی را به عدد صحیح تبدیل می‌کند.

    ویرگول و «ریال» نادیده گرفته می‌شوند. اعشار قبول نیست تا ۱٫۵ ریال
    با گرد کردن، کانال را عوض نکند. بالاتر از سقف اسمی ساتنا هنوز عدد معتبر است؛
    کانال همان ساتنا می‌ماند و پرچم مدارک جداگانه روشن می‌شود.
    """
    text = raw.translate(_DIGIT_FOLD).strip().lower()
    for word in ("ریال", "rial", "irr"):
        text = text.replace(word, "")
    for separator in (",", "،", "٬", "_", " "):
        text = text.replace(separator, "")
    if not text:
        return None, "مبلغ خالی است."
    if not text.isdigit():
        return None, "مبلغ باید یک عدد صحیح به ریال باشد، بدون اعشار."
    if len(text) > _MAX_AMOUNT_DIGITS:
        return None, f"مبلغ از سقف {format_rial(SATNA_MAX_RIAL)} ریال بیشتر است."
    amount = int(text)
    if amount < 1:
        return None, "مبلغ باید حداقل ۱ ریال باشد."
    return amount, None


def parse_destination(raw: str) -> tuple[Destination | None, str | None]:
    """شبا یا شماره حساب مهر را از متن کاربر جدا می‌کند.

    هر چیزی که با IR شروع شود فقط به‌عنوان شبا بررسی می‌شود، حتی اگر رقم کنترلش غلط باشد؛
    آن را به حساب داخلی تبدیل نمی‌کنیم. شمارهٔ بدون IR اگر طولش در بازهٔ حساب مهر باشد
    داخلی است.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, "شماره شبا یا حساب ذینفع خالی است."

    compact = raw.translate(_DIGIT_FOLD).upper()
    compact = compact.replace("شبا", "").replace("IBAN", "")
    compact = "".join(char for char in compact if char.isalnum())
    if compact.startswith("IR"):
        check = validate_sheba(raw)
        if not check.valid:
            if check.reason == "checksum":
                return None, "شماره شبا نامعتبر است. رقم کنترلی درست نیست."
            return None, "شماره شبا باید با IR شروع شود و ۲۴ رقم داشته باشد."
        # بخش عددی بعد از IR بیست‌وچهار رقم است.
        # رقم ۱ و ۲ کنترل IBAN است. رقم ۳ تا ۵ کد بانک است.
        # اندیس [2:5] همان جایگاه سوم تا پنجم است، چون شمارش از صفر است.
        digits = check.normalized[2:]
        bank_code = digits[2:5]
        return Destination("sheba", check.normalized, bank_code), None

    if not compact.isdigit():
        return None, "شماره شبا یا حساب ذینفع نامعتبر است."
    if len(compact) == CARD_DIGITS:
        return None, "شماره کارت پذیرفته نیست. شبا یا شماره حساب بانک مهر را بفرستید."
    if len(compact) == 24:
        return None, "شماره شبا باید با IR شروع شود."
    if ACCOUNT_MIN_DIGITS <= len(compact) <= ACCOUNT_MAX_DIGITS:
        return Destination("account", compact, None), None
    return (
        None,
        "شماره حساب بانک مهر باید بین ۸ و ۱۸ رقم باشد. "
        "اگر شبا دارید آن را با IR بفرستید.",
    )


def channel_for(destination: Destination, amount: int) -> str:
    """کانال را از مقصد و مبلغ برمی‌گرداند. مبلغ باید از قبل حداقل ۱ ریال باشد.

    حساب داخلی و شبای ۰۶۰ همیشه داخلی‌اند. مبلغشان را به پایا و ساتنا برنمی‌گردانیم.
    شبای بانک دیگر تا سقف پایا (شامل) پایا است و از آن به بعد ساتنا، حتی بالای ۵ میلیارد.
    """
    if amount < 1:
        raise ValueError("amount out of range")
    if destination.kind == "account" or destination.bank_code == MEHR_BANK_CODE:
        return "internal"
    if amount <= PAYA_MAX_RIAL:
        return "paya"
    return "satna"


def validate_single(name: str, account_raw: str, amount_raw: str) -> tuple[TransferRow | None, str | None]:
    """یک انتقال تکی را با همان قاعدهٔ سطر اکسل می‌سنجد. فیلد اختیاری در ویزارد پرسیده نمی‌شود."""
    name_error = validate_beneficiary_name(name)
    destination, destination_error = parse_destination(account_raw)
    amount, amount_error = parse_amount(amount_raw)
    problems = [item for item in (name_error, destination_error, amount_error) if item]
    if problems or destination is None or amount is None:
        return None, "\n".join(problems) or "اطلاعات انتقال ناقص است."
    cleaned = " ".join(name.split())
    return (
        TransferRow(
            excel_row=0,
            name=cleaned,
            national_id="",
            account=destination.normalized,
            amount=amount,
            deposit_id="",
            description="",
            channel=channel_for(destination, amount),
        ),
        None,
    )


def _alias_index() -> dict[str, str]:
    """هر عنوان تا شده را به یک فیلد وصل می‌کند. عنوان تکراری بین دو فیلد خطای برنامه‌نویسی است."""
    index: dict[str, str] = {}
    for field, aliases in _HEADER_ALIASES.items():
        for alias in aliases:
            folded = fold_header(alias)
            if folded in index and index[folded] != field:
                raise RuntimeError(f"ambiguous header alias: {alias}")
            index[folded] = field
    return index


_ALIAS_INDEX = _alias_index()


def map_headers(cells: list[str]) -> tuple[dict[str, int] | None, str | None]:
    """جای هر ستون را از ردیف عنوان پیدا می‌کند. ستون ناشناس نادیده گرفته می‌شود."""
    found: dict[str, int] = {}
    for index, cell in enumerate(cells):
        folded = fold_header(cell)
        if not folded:
            continue
        field = _ALIAS_INDEX.get(folded)
        if field is None:
            continue
        if field in found:
            return None, f"ستون «{FIELD_LABELS[field]}» بیش از یک بار در عنوان آمده است."
        found[field] = index
    missing = [FIELD_LABELS[field] for field in _REQUIRED_FIELDS if field not in found]
    if missing:
        joined = "، ".join(missing)
        return None, f"ستون‌های لازم در ردیف عنوان پیدا نشد: {joined}."
    return found, None


def _field(cells: list[str], mapping: dict[str, int], field: str) -> str:
    index = mapping.get(field)
    if index is None or index >= len(cells):
        return ""
    return cells[index]


def parse_data_row(
    excel_row: int,
    cells: list[str],
    mapping: dict[str, int],
) -> tuple[TransferRow | None, list[str]]:
    """یک سطر داده را می‌سنجد. چند خطا با هم برمی‌گردند تا مشتری یک‌بار فایل را اصلاح کند."""
    prefix = f"سطر {excel_row}"
    problems: list[str] = []

    name = " ".join(_field(cells, mapping, "name").split())
    name_error = validate_beneficiary_name(name)
    if name_error:
        problems.append(f"{prefix}: {name_error}")

    national_id, national_error = parse_national_id(_field(cells, mapping, "national_id"))
    if national_error:
        problems.append(f"{prefix}: {national_error}")

    destination, destination_error = parse_destination(_field(cells, mapping, "account"))
    if destination_error:
        problems.append(f"{prefix}: {destination_error}")

    amount, amount_error = parse_amount(_field(cells, mapping, "amount"))
    if amount_error:
        problems.append(f"{prefix}: {amount_error}")

    deposit_id, deposit_error = parse_deposit_id(_field(cells, mapping, "deposit_id"))
    if deposit_error:
        problems.append(f"{prefix}: {deposit_error}")

    description, description_error = parse_description(_field(cells, mapping, "description"))
    if description_error:
        problems.append(f"{prefix}: {description_error}")

    if problems or destination is None or amount is None:
        return None, problems

    return (
        TransferRow(
            excel_row=excel_row,
            name=name,
            national_id=national_id,
            account=destination.normalized,
            amount=amount,
            deposit_id=deposit_id,
            description=description,
            channel=channel_for(destination, amount),
        ),
        [],
    )


def format_validation_errors(errors: list[str]) -> str:
    """چند خطای اول را نشان می‌دهد تا پیام از سقف بله رد نشود."""
    shown = errors[:_MAX_ERROR_LINES]
    lines = ["این فایل برای انتقال وجه پذیرفته نشد و برای مدیر ارسال نمی‌شود.", *shown]
    extra = len(errors) - len(shown)
    if extra:
        lines.append(f"و {extra} خطای دیگر.")
    return "\n".join(lines)


def _tsv_field(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def format_transfer_table(rows: list[TransferRow], *, truncated: bool) -> str:
    """جدول نهایی برای مدیر: هر سطر یک انتقال و ستون آخر کانال همان سطر."""
    lines = [
        f"سطر معتبر: {len(rows)}. کانال هر سطر از روی شبا یا حساب و مبلغ تعیین شده است.",
        "\t".join(OUTPUT_COLUMNS),
    ]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    str(row.excel_row),
                    _tsv_field(row.name),
                    row.national_id,
                    row.account,
                    str(row.amount),
                    row.deposit_id,
                    _tsv_field(row.description),
                    row.channel_label,
                ]
            )
        )
    if truncated:
        lines.append(_TRUNCATION_NOTE)
    return "\n".join(lines)


def collect_transfer_rows(rows: list[tuple[int, list[str]]]) -> list[TransferRow]:
    """ردیف‌های شیت اول را می‌سنجد. اولین ردیف غیرخالی عنوان است.

    اگر حتی یک سطر خطا داشته باشد کل فایل رد می‌شود تا چیز ناقصی برای مدیر نرود.
    """
    if not rows:
        raise TransferValidationError(
            "فایل اکسل سطری ندارد. ردیف عنوان و حداقل یک ذینفع لازم است."
        )
    _header_row, header_cells = rows[0]
    mapping, header_error = map_headers(header_cells)
    if mapping is None:
        raise TransferValidationError(header_error or "ردیف عنوان فایل شناخته نشد.")
    data = rows[1:]
    if not data:
        raise TransferValidationError("فایل فقط ردیف عنوان دارد. حداقل یک سطر انتقال لازم است.")

    built: list[TransferRow] = []
    errors: list[str] = []
    for excel_row, cells in data:
        row, row_errors = parse_data_row(excel_row, cells, mapping)
        if row_errors:
            errors.extend(row_errors)
        elif row is not None:
            built.append(row)
    if errors:
        raise TransferValidationError(format_validation_errors(errors))
    return built


def rows_by_channel(rows: list[TransferRow]) -> dict[str, list[TransferRow]]:
    """سطرها را به سه فهرست جدا می‌کند تا هر کانال فایل خودش را بگیرد."""
    grouped: dict[str, list[TransferRow]] = {"internal": [], "paya": [], "satna": []}
    for row in rows:
        grouped.setdefault(row.channel, []).append(row)
    return grouped


def any_needs_docs(rows: list[TransferRow]) -> bool:
    """اگر حتی یک سطر مدارک بخواهد، بعد از ساخت فایل‌ها از مشتری عکس یا PDF می‌پرسیم."""
    return any(row.needs_docs for row in rows)


def format_channel_companion(rows: list[TransferRow], *, truncated: bool) -> str | None:
    """متنی که کنار فایل‌های ccti برای مدیر می‌ماند.

    الگوی ccti جای شرح ندارد. اگر شرح را داخل XML بگذاریم واردکنندهٔ بانک ممکن است فایل را رد کند،
    برای همین شرح این‌جا می‌آید. خود سطرهای داخلی و ساتنا فایل ccti جدا دارند؛
    این متن رونوشت خوانا برای شعبه است، نه جایگزین آن فایل‌ها.
    اگر همه‌چیز پایا باشد و شرح و سقف حذف‌شده‌ای در کار نباشد، None برمی‌گردد تا فایل متنی اضافه نسازیم.
    """
    others = [row for row in rows if row.channel != "paya"]
    notes = [row for row in rows if row.channel == "paya" and row.description]
    if not others and not notes and not truncated:
        return None
    parts: list[str] = []
    if others:
        parts.append("رونوشت سطرهای داخلی و ساتنا. فایل ccti هر کانال جداگانه هم ارسال شده است.")
        parts.append(format_transfer_table(others, truncated=False))
    if notes:
        parts.append("شرح سطرهای پایا (در فایل ccti نیست):")
        for row in notes:
            parts.append(f"سطر {row.excel_row}: {row.name} — {_tsv_field(row.description)}")
    if truncated:
        parts.append(_TRUNCATION_NOTE)
    return "\n".join(parts)


def transfers_from_table(rows: list[tuple[int, list[str]]], *, truncated: bool) -> str:
    """همان جدول متنی کامل، برای تست و برای وقتی که هنوز فایلی ساخته نشده."""
    return format_transfer_table(collect_transfer_rows(rows), truncated=truncated)
