"""پرسش‌های متداول شعبه، جدا از متن‌های تکی.

متن‌های معمولی در کلید bot_texts هستند و هر کدام یک رشته است.
پرسش و پاسخ چندتاست و مدیر باید بتواند یکی را حذف کند، برای همین
سند جداگانه‌ای در کلید bot_faq نگه می‌داریم:

- items: ترتیب نمایش، هر عضو id و question و answer
- hidden: شناسهٔ پیش‌فرض‌هایی که مدیر حذف کرده است

اگر hidden نبود، استقرار بعدی همان پیش‌فرض را دوباره ته فهرست می‌گذاشت
و حذف مدیر بی‌اثر می‌شد. پرسش تازه‌ای که فقط در کد اضافه شود
و در hidden نباشد، مثل کلید تازهٔ متن‌ها، به سند قبلی اضافه می‌شود.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from texts import KeyValue

# سقف دکمهٔ کیبورد را کوتاه نگه می‌داریم تا برچسب در بله نشکند.
_BUTTON_LIMIT = 64
# ده پرسش برای یک شعبه کافی است و کیبورد را از حد پیام رد نمی‌کند.
MAX_FAQ_ITEMS = 10
MAX_QUESTION_LENGTH = 200
MAX_ANSWER_LENGTH = 1500

_KV_KEY = "bot_faq"

# همان یکدست‌سازی bot.norm تا این ماژول به bot وابسته نشود و چرخهٔ واردات پیش نیاید.
_LETTER_FOLD = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": "", "\u200d": ""})
_DIGIT_FOLD = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class FaqFullError(Exception):
    """فهرست به سقف رسیده است. بازو این را به جملهٔ فارسی تبدیل می‌کند، نه به خطای ورکر."""


@dataclass(frozen=True)
class FaqItem:
    """یک پرسش. id پایدار است تا ویرایش، متن را با ردیف قبلی عوض کند نه با شماره."""

    id: str
    question: str
    answer: str


# متن‌ها نمونهٔ قابل‌ویرایش‌اند. عدد کارمزد و ساعت قطعی عمداً این‌جا نیست
# تا با بخشنامهٔ بعدی غلط نشوند؛ شعبه همان‌ها را در پاسخ خودش می‌نویسد.
DEFAULT_FAQ: tuple[FaqItem, ...] = (
    FaqItem(
        "open-account",
        "مدارک افتتاح حساب چیست؟",
        "برای حساب شخصی معمولاً اصل کارت ملی و شناسنامه لازم است. "
        "حساب حقوقی مدارک ثبت شرکت، شناسهٔ ملی و معرفی‌نامهٔ صاحبان امضا می‌خواهد. "
        "فهرست نهایی را همان روز از شعبهٔ بانک مهر بپرسید؛ این متن نمونه است.",
    ),
    FaqItem(
        "settlement",
        "واریز حقوق کی به حساب می‌نشیند؟",
        "فایل حقوق بعد از بررسی شعبه در چرخهٔ پایا یا ساتنا ارسال می‌شود. "
        "تحویل تا پایان ساعت کار معمولاً به اولین چرخهٔ همان روز کاری می‌رسد. "
        "تعطیل رسمی به روز کاری بعد می‌افتد. ساعت قطعی را شعبه می‌گوید.",
    ),
    FaqItem(
        "fee",
        "کارمزد واریز حقوق چقدر است؟",
        "کارمزد طبق تعرفهٔ بانک مرکزی و بخشنامهٔ بانک مهر است و برای پایا، ساتنا و انتقال داخلی یکی نیست. "
        "مبلغ را پیش از تأیید فایل از شعبه بپرسید. این بازو کارمزد را حساب نمی‌کند.",
    ),
    FaqItem(
        "sheba-docs",
        "برای ثبت شبا چه مدرکی لازم است؟",
        "شبا را از روی کارت یا همراه‌بانک همان حساب بردارید. "
        "اگر شعبه بخواهد، تصویر کارت ملی و شماره حساب صاحب شبا را هم می‌گیرد. "
        "دکمهٔ اعتبارسنجی شبا فقط شکل شماره را بررسی می‌کند و باز بودن حساب را تأیید نمی‌کند.",
    ),
    FaqItem(
        "hours",
        "ساعت کار شعبه چیست؟",
        "مراجعهٔ حضوری معمولاً شنبه تا چهارشنبه حدود ۸ تا ۱۵ است. "
        "پنجشنبه اغلب کوتاه‌تر است و جمعه تعطیل است. "
        "این ساعت نمونه است؛ تابلو یا تلفن شعبهٔ خودتان ملاک است.",
    ),
    FaqItem(
        "payroll-file",
        "فایل انتقال را چطور بفرستم؟",
        "دکمهٔ «📄 دریافت نمونه اکسل» را بزنید. "
        "ستون‌های نام ذینفع، شماره شبا یا حساب، و مبلغ به ریال لازم است. "
        "کدملی، شناسه واریز و شرح اختیاری است. فایل xlsx را از «📂 انتقال وجه گروهی» بفرستید. "
        "اگر سطرها معتبر باشند، شما تأیید می‌گیرید و متن برای مسئول شعبه می‌رود.",
    ),
    FaqItem(
        "trace",
        "اگر مبلغ به حساب ننشست چه کنم؟",
        "نام گیرنده، مبلغ، شبا و ساعت ارسال فایل را به شعبه بدهید. "
        "اصلاح مبلغ یا شبا با فایل جدید یا مراجعهٔ حضوری است. "
        "این بازو مانده و گردش حساب نشان نمی‌دهد.",
    ),
    FaqItem(
        "limits",
        "سقف انتقال روزانه چقدر است؟",
        "در این بازو، شبای بانک دیگر تا ۲ میلیارد ریال پایا و از آن بیشتر تا ۵ میلیارد ریال ساتنا حساب می‌شود. "
        "حساب یا شبای بانک مهر (کد ۰۶۰) داخلی است. "
        "سقف واقعی شعبه ممکن است طبق بخشنامه کمتر باشد؛ عدد قطعی را شعبه می‌گوید.",
    ),
)

# اگر پرسش و پاسخ هنوز عین پیش‌فرض نسخهٔ قبل باشد، متن جدید را می‌گذاریم.
# پاسخی که مدیر خودش نوشته با این جفت‌ها یکی نیست و دست نمی‌خورد.
_PREVIOUS_FAQ: dict[str, frozenset[tuple[str, str]]] = {
    "payroll-file": frozenset(
        {
            (
                "فایل حقوق را چطور بفرستم؟",
                "دکمهٔ «نمونه فایل برای واریز حقوق» را بزنید. "
                "ستون‌های name (نام)، amount (مبلغ به ریال) و sheba را پر کنید و فایل xlsx را در همین گفتگو بفرستید. "
                "شما یک پیام تأیید می‌گیرید و متن فایل برای مسئول شعبه ارسال می‌شود.",
            ),
            (
                "فایل انتقال را چطور بفرستم؟",
                "دکمهٔ «دریافت نمونه اکسل» را بزنید. "
                "ستون‌های نام ذینفع، شماره شبا یا حساب، و مبلغ به ریال لازم است. "
                "کدملی، شناسه واریز و شرح اختیاری است. فایل xlsx را از «انتقال وجه گروهی» بفرستید. "
                "اگر سطرها معتبر باشند، شما تأیید می‌گیرید و متن برای مسئول شعبه می‌رود.",
            ),
        }
    ),
    "limits": frozenset(
        {
            (
                "سقف انتقال روزانه چقدر است؟",
                "سقف پایا و ساتنا به نوع حساب و بخشنامهٔ روز بستگی دارد و عدد ثابتی این‌جا نیست "
                "تا با بخشنامهٔ جدید غلط نشود. برای مبلغ بالاتر از سقف، شعبه مسیر جدا (مثلاً ساتنا) را می‌گوید.",
            )
        }
    ),
}

_DEFAULT_BY_ID: dict[str, FaqItem] = {item.id: item for item in DEFAULT_FAQ}


def fold_text(text: str) -> str:
    """فاصله، ی/ک و رقم فارسی را یکدست می‌کند تا «حذف ۲» و «حذف 2» یکی شوند."""
    return " ".join(text.translate(_LETTER_FOLD).split()).translate(_DIGIT_FOLD)


def fresh_faq_id(items: list[FaqItem]) -> str:
    """شناسهٔ پرسش تازه‌ای که مدیر از بازو می‌سازد. با پیش‌فرض‌های کد قاطی نمی‌شود."""
    used = {item.id for item in items}
    number = 1
    while f"custom-{number}" in used:
        number += 1
    return f"custom-{number}"


def faq_button_label(index: int, question: str) -> str:
    """برچسب دکمه. شماره اول می‌ماند تا اگر متن کوتاه شد همان ردیف پیدا شود."""
    prefix = f"{index}. "
    body = " ".join(question.split())
    if len(prefix) + len(body) <= _BUTTON_LIMIT:
        return prefix + body
    room = _BUTTON_LIMIT - len(prefix) - 1
    if room < 1:
        return prefix.strip()
    return prefix + body[:room] + "…"


def match_faq_item(text: str, items: list[FaqItem], *, allow_number: bool) -> FaqItem | None:
    """پرسش را از روی برچسب دکمه، خود سؤال، یا شماره پیدا می‌کند.

    شماره فقط داخل فهرست پرسش‌ها پذیرفته می‌شود. بیرون از آن، فرستادن «۱»
    نباید بی‌خبر اولین پاسخ را باز کند.
    """
    folded = fold_text(text)
    if not folded:
        return None
    if allow_number and folded.isdigit():
        index = int(folded)
        if 1 <= index <= len(items):
            return items[index - 1]
        return None
    for index, item in enumerate(items, start=1):
        if folded == fold_text(item.question):
            return item
        if folded == fold_text(faq_button_label(index, item.question)):
            return item
    return None


def parse_faq_admin_input(
    text: str,
    *,
    add_word: str,
    delete_word: str,
    count: int,
) -> tuple[str, int | None] | None:
    """دستور منوی ویرایش پرسش را به add / edit / delete / invalid تبدیل می‌کند.

    None یعنی اصلاً شبیه دستور نبود. invalid یعنی شماره خارج از فهرست بود.
    """
    folded = fold_text(text)
    if not folded:
        return None
    if folded == fold_text(add_word):
        return ("add", None)
    delete_norm = fold_text(delete_word)
    # «حذف ۲» و «حذف۲» هر دو حذف‌اند. خود کلمهٔ تنها کافی نیست چون شماره ندارد.
    if delete_norm and folded.startswith(delete_norm) and folded != delete_norm:
        rest = folded[len(delete_norm) :].strip()
        if rest.isdigit():
            number = int(rest)
            if 1 <= number <= count:
                return ("delete", number)
            return ("invalid", None)
        return None
    if folded.isdigit():
        number = int(folded)
        if count and 1 <= number <= count:
            return ("edit", number)
        return ("invalid", None)
    return None


def format_faq_menu(intro: str, items: list[FaqItem]) -> str:
    """فهرست شماره‌دار برای مشتری. دکمه‌ها همان شماره‌ها را تکرار می‌کنند."""
    if not items:
        return intro
    lines = [intro, ""]
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item.question}")
    return "\n".join(lines)


def format_faq_answer(item: FaqItem) -> str:
    """پرسش را بالای پاسخ تکرار می‌کنیم تا بعد از باز شدن، سؤال گم نشود."""
    return f"{item.question}\n\n{item.answer}"


def faq_keyboard(items: list[FaqItem], back_to_list: str, back_to_menu: str) -> dict:
    """کیبورد پاسخ‌نامه: هر پرسش یک ردیف، بعد بازگشت به فهرست و منوی اصلی."""
    rows = [[faq_button_label(index, item.question)] for index, item in enumerate(items, start=1)]
    rows.append([back_to_list])
    rows.append([back_to_menu])
    return {"keyboard": rows}


class FaqRepository:
    """خواندن و نوشتن سند bot_faq. منطق گفتگو فقط همین کلاس را می‌بیند."""

    def __init__(self, kv: KeyValue) -> None:
        self.kv = kv

    async def list_items(self) -> list[FaqItem]:
        """فهرست مؤثر. بار اول پیش‌فرض‌ها را می‌نویسد."""
        items, _hidden, _changed = await self._load(persist=True)
        return items

    async def upsert(self, item: FaqItem) -> None:
        """پرسش موجود را عوض می‌کند یا اگر جا باشد به ته فهرست اضافه می‌کند."""
        items, hidden, _changed = await self._load(persist=False)
        for index, current in enumerate(items):
            if current.id == item.id:
                items[index] = item
                hidden.discard(item.id)
                await self._write(items, hidden)
                return
        if len(items) >= MAX_FAQ_ITEMS:
            raise FaqFullError()
        items.append(item)
        hidden.discard(item.id)
        await self._write(items, hidden)

    async def delete(self, item_id: str) -> bool:
        """پرسش را برمی‌دارد. پیش‌فرض حذف‌شده را در hidden می‌گذارد تا دوباره سبز نشود."""
        items, hidden, _changed = await self._load(persist=False)
        kept = [item for item in items if item.id != item_id]
        if len(kept) == len(items):
            return False
        if item_id in _DEFAULT_BY_ID:
            hidden.add(item_id)
        await self._write(kept, hidden)
        return True

    async def _load(self, *, persist: bool) -> tuple[list[FaqItem], set[str], bool]:
        raw = await self.kv.get(_KV_KEY)
        if not raw:
            items = list(DEFAULT_FAQ)
            if persist:
                await self._write(items, set())
            return items, set(), True

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("items"), list):
            items = list(DEFAULT_FAQ)
            if persist:
                await self._write(items, set())
            return items, set(), True

        items = _parse_items(parsed.get("items"))
        hidden = _parse_hidden(parsed.get("hidden"))
        changed = _upgrade_unchanged_defaults(items)
        changed = _merge_new_defaults(items, hidden) or changed
        if changed and persist:
            await self._write(items, hidden)
        return items, hidden, changed

    async def _write(self, items: list[FaqItem], hidden: set[str]) -> None:
        # hidden را مرتب می‌نویسیم تا تست و diff هر بار شکل دیگری نبینند.
        payload = {
            "items": [
                {"id": item.id, "question": item.question, "answer": item.answer} for item in items
            ],
            "hidden": sorted(hidden),
        }
        await self.kv.put(_KV_KEY, json.dumps(payload, ensure_ascii=False))


def _parse_items(raw_items: object) -> list[FaqItem]:
    """ردیف خراب را رد می‌کنیم تا یک پرسش بد، کل فهرست را خالی نکند."""
    if not isinstance(raw_items, list):
        return []
    items: list[FaqItem] = []
    seen: set[str] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        item_id = entry.get("id")
        question = entry.get("question")
        answer = entry.get("answer")
        if not isinstance(item_id, str) or not item_id.strip():
            continue
        if not isinstance(question, str) or not question.strip():
            continue
        if not isinstance(answer, str) or not answer.strip():
            continue
        item_id = item_id.strip()[:40]
        if item_id in seen:
            continue
        seen.add(item_id)
        items.append(
            FaqItem(
                id=item_id,
                question=question.strip()[:MAX_QUESTION_LENGTH],
                answer=answer.strip()[:MAX_ANSWER_LENGTH],
            )
        )
    return items


def _parse_hidden(raw_hidden: object) -> set[str]:
    if not isinstance(raw_hidden, list):
        return set()
    hidden: set[str] = set()
    for value in raw_hidden:
        if isinstance(value, str) and value.strip():
            hidden.add(value.strip()[:40])
    return hidden


def _upgrade_unchanged_defaults(items: list[FaqItem]) -> bool:
    """پاسخ پیش‌فرض نسخهٔ قبل را با متن فعلی عوض می‌کند. True یعنی سند باید دوباره نوشته شود."""
    changed = False
    for index, item in enumerate(items):
        previous = _PREVIOUS_FAQ.get(item.id)
        default = _DEFAULT_BY_ID.get(item.id)
        if not previous or default is None:
            continue
        if (item.question, item.answer) not in previous:
            continue
        if item.question == default.question and item.answer == default.answer:
            continue
        items[index] = default
        changed = True
    return changed


def _merge_new_defaults(items: list[FaqItem], hidden: set[str]) -> bool:
    """پیش‌فرض تازه‌ای که مدیر حذفش نکرده را ته فهرست می‌گذارد. True یعنی سند عوض شد."""
    present = {item.id for item in items}
    changed = False
    for default in DEFAULT_FAQ:
        if default.id in present or default.id in hidden:
            continue
        items.append(default)
        present.add(default.id)
        changed = True
    return changed
