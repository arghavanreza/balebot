"""آمار روزانهٔ مدیر و زمان تهران.

ایران از سال ۱۴۰۱ ساعت تابستانی ندارد، پس اختلاف با UTC همیشه ۳ ساعت و ۳۰ دقیقه است.
zoneinfo و بستهٔ tzdata را صدا نمی‌زنیم تا ورکر پایتون کلادفلر به دادهٔ منطقهٔ زمانی وابسته نباشد.

«امروز» از ۰۰:۰۰ تا ۲۴:۰۰ به وقت تهران است. ستون‌های زمانی در D1 متن UTC با پسوند Z هستند
(مثل 2026-10-01T20:30:00Z). چون این قالب طول ثابت و مرتب‌شدنی است، فیلتر بازه با
مقایسهٔ متنی SQL کافی است و تابع تاریخ SQLite لازم نیست.

کاربر فعال امروز: last_seen_at داخل همین بازه.
کاربر تازه‌وارد امروز: first_seen_at داخل همین بازه.
رویدادها در جدول events هستند، نه با شمردن دوبارهٔ پیام‌ها.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# اختلاف رسمی ایران با UTC. timedelta را خودمان می‌سازیم تا به tzdata نیاز نباشد.
TEHRAN = timezone(timedelta(hours=3, minutes=30))

# کدهایی که record_event می‌پذیرد. چیز دیگر در جدول نمی‌نشیند تا آمار غریبه جمع نشود.
EVENT_KINDS = frozenset({"excel", "faq", "sheba", "sample"})

# متن پرسش را کوتاه نگه می‌داریم تا GROUP BY روی رشته‌های بلند نرود.
FAQ_DETAIL_LIMIT = 100

# این دو جمله فقط جواب /stats هستند و عمداً داخل منوی ویرایش متن نیستند.
STATS_DB_UNAVAILABLE = (
    "پایگاه آمار وصل نیست.\n"
    "بعد از ساخت D1 و اعمال مهاجرت‌ها، این دستور شمارش امروز را نشان می‌دهد."
)
STATS_FAILED = "خواندن آمار ممکن نشد. کمی بعد دوباره /stats را بفرستید."

# کاربران فعال: آخرین بازدیدشان در بازهٔ امروز تهران است.
COUNT_ACTIVE_SQL = """
SELECT COUNT(*) AS n FROM users
WHERE last_seen_at >= ? AND last_seen_at < ?
""".strip()

# کاربران تازه‌وارد: اولین بازدیدشان در همان بازه است. با فعال‌ها یکی نیست.
COUNT_NEW_SQL = """
SELECT COUNT(*) AS n FROM users
WHERE first_seen_at >= ? AND first_seen_at < ?
""".strip()

# یک شمارش برای هر kind. kindهای غایب در نتیجه یعنی صفر، نه خطا.
COUNT_KINDS_SQL = """
SELECT kind, COUNT(*) AS n FROM events
WHERE created_at >= ? AND created_at < ?
GROUP BY kind
""".strip()

# پرتکرارترین پرسش‌های امروز. detail متن کوتاه پرسش است.
# مرتب‌سازی دوم روی خود متن است تا اگر تعداد برابر بود ترتیب ثابت بماند.
TOP_FAQ_SQL = """
SELECT detail, COUNT(*) AS n FROM events
WHERE kind = 'faq'
  AND created_at >= ? AND created_at < ?
  AND detail IS NOT NULL
  AND detail != ''
GROUP BY detail
ORDER BY n DESC, detail ASC
LIMIT 5
""".strip()

INSERT_EVENT_SQL = """
INSERT INTO events (user_id, kind, detail, created_at) VALUES (?, ?, ?, ?)
""".strip()


@dataclass(frozen=True)
class StatsSnapshot:
    """نتیجهٔ یک بازه. counts همیشه هر چهار kind را دارد، حتی اگر صفر باشند."""

    active_users: int
    new_users: int
    counts: dict[str, int]
    top_faq: list[tuple[str, int]]
    # False یعنی جدول events هنوز نیست. شمارش کاربران در همین شیء معتبر است.
    events_ready: bool = True


def parse_utc_iso(value: str) -> datetime:
    """متن ISO را به لحظهٔ UTC تبدیل می‌کند. پسوند Z و افست +00:00 هر دو پذیرفته می‌شوند."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_utc_z(moment: datetime) -> str:
    """همان قالب utc_now_iso: بدون کسری ثانیه و با پسوند Z، تا مقایسه با ستون‌های TEXT جور باشد."""
    utc = moment.astimezone(timezone.utc).replace(microsecond=0)
    return utc.isoformat().replace("+00:00", "Z")


def tehran_day_bounds(now_iso: str) -> tuple[str, str, str]:
    """ابتدا و انتهای روز تهران را به UTC برمی‌گرداند، به‌همراه تاریخ همان روز.

    انتهاexclusive است: آخرین لحظهٔ روز در مقایسهٔ «کوچک‌تر از end» جا می‌شود
    و نیمه‌شب فردا داخل امروز حساب نمی‌شود.
    """
    local = parse_utc_iso(now_iso).astimezone(TEHRAN)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return to_utc_z(start_local), to_utc_z(end_local), start_local.date().isoformat()


def format_tehran_stamp(now_iso: str) -> str:
    """یک لحظه برای پیام مدیر: ساعت تهران و همان لحظه به UTC تا مبهم نماند."""
    moment = parse_utc_iso(now_iso)
    local = moment.astimezone(TEHRAN)
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} به وقت تهران ({to_utc_z(moment)} UTC)"


def clip_detail(value: object) -> str | None:
    """متن رویداد را یک‌خطی و کوتاه می‌کند. خالی یعنی NULL در ستون detail."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned[:FAQ_DETAIL_LIMIT]


def prepare_event(
    user_id: object,
    kind: object,
    created_at: object,
    detail: object = None,
) -> tuple[int, str, str, str | None] | None:
    """رویداد را قبل از درج چک می‌کند. None یعنی عمداً نوشته نمی‌شود."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        return None
    if not isinstance(kind, str) or kind not in EVENT_KINDS:
        return None
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    return user_id, kind, created_at.strip(), clip_detail(detail)


def format_stats(snapshot: StatsSnapshot, *, day_label: str) -> str:
    """متن فارسی /stats. تعریف «امروز» داخل خود پیام است تا مدیر به کد برنگردد."""
    lines = [
        f"آمار امروز ({day_label}، وقت تهران)",
        "",
        "بازه از نیمه‌شب تا نیمه‌شب بعد به وقت تهران است (UTC+03:30، بدون ساعت تابستانی).",
        "کاربر فعال: last_seen_at او در این بازه است.",
        "کاربر تازه‌وارد: first_seen_at او در این بازه است.",
        "",
        f"کاربران فعال امروز: {snapshot.active_users}",
        f"کاربران تازه‌وارد امروز: {snapshot.new_users}",
        "",
    ]
    if not snapshot.events_ready:
        lines.append("شمارش رویدادها ممکن نشد. مهاجرت جدول events را اعمال کنید.")
        return "\n".join(lines)
    counts = snapshot.counts
    lines.extend(
        [
            f"ارسال اکسل امروز: {counts.get('excel', 0)}",
            f"نمونهٔ فایل امروز: {counts.get('sample', 0)}",
            f"شروع اعتبارسنجی شبا امروز: {counts.get('sheba', 0)}",
            f"باز شدن پاسخ پرسش امروز: {counts.get('faq', 0)}",
            "",
            "پرسش‌های پرتکرار امروز:",
        ]
    )
    if not snapshot.top_faq:
        lines.append("امروز پاسخی از پرسش‌ها باز نشده است.")
    else:
        for index, (question, count) in enumerate(snapshot.top_faq, start=1):
            lines.append(f"{index}. {question} — {count} بار")
    return "\n".join(lines)
