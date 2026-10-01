"""ذخیرهٔ کاربران بازو در پایگاه D1.

D1 پایگاه SQLite کلادفلر است که کنار ورکر قرار می‌گیرد. باندینگش در
wrangler.jsonc با نام DB تعریف شده است. این ماژول دو کار دارد:

- با هر پیام یا callback، کاربر را درج یا به‌روز کند (upsert).
- برای مدیر، تازه‌ترین کاربران را از همان جدول بخواند.

منطق گفتگو به خود D1 وصل نیست. تست‌ها از MemoryUserStore استفاده می‌کنند
و ورکر از D1UserStore. هر دو touch، list_recent، get و set_last_action را دارند.

ستون last_action (مهاجرت ۰۰۰۲) فقط آخرین کار را نگه می‌دارد: sample، sheba،
faq یا excel. خالی بودنش یعنی موضوعی برای «خوش برگشتی» ساخته نمی‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol

# سقف فهرست /users تا پاسخ از حد پیام بله (حدود ۴۰۹۶ نویسه) رد نشود.
RECENT_USER_LIMIT = 20

# این دو متن فقط جواب دستور مدیر هستند و عمداً در منوی «ویرایش متن» نیستند
# تا فهرست کلیدهای مشتری شلوغ نشود.
USERS_DB_UNAVAILABLE = (
    "پایگاه کاربران وصل نیست.\n"
    "بعد از ساخت D1 و قرار دادن باندینگ DB، این دستور فهرست را نشان می‌دهد."
)
USERS_LIST_FAILED = "خواندن فهرست کاربران ممکن نشد. کمی بعد دوباره /users را بفرستید."

# درج کاربر تازه، یا به‌روزرسانی همان ردیف اگر user_id از قبل باشد.
# first_seen_at در بخش UPDATE نیست تا تاریخ اولین بازدید حفظ شود.
# message_count را این‌جا زیاد می‌کنیم، نه با مقدار فرستاده‌شده، تا شمارش دقیق بماند.
UPSERT_SQL = """
INSERT INTO users (
    user_id, username, first_name, last_name, language_code,
    is_admin, first_seen_at, last_seen_at, message_count
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
ON CONFLICT(user_id) DO UPDATE SET
    username = excluded.username,
    first_name = excluded.first_name,
    last_name = excluded.last_name,
    language_code = excluded.language_code,
    is_admin = excluded.is_admin,
    last_seen_at = excluded.last_seen_at,
    message_count = users.message_count + 1
""".strip()

# تازه‌ترین بازدیدها بالا باشند. user_id ترتیب را در زمان برابر ثابت می‌کند.
# last_action عمداً این‌جا نیست تا فهرست /users قبل از مهاجرت ۰۰۰۲ هم کار کند.
LIST_RECENT_SQL = """
SELECT user_id, username, first_name, last_name, language_code,
       is_admin, first_seen_at, last_seen_at, message_count
FROM users
ORDER BY last_seen_at DESC, user_id DESC
LIMIT ?
""".strip()

# خواندن یک نفر برای خوش‌آمد. last_action همان ستون مهاجرت ۰۰۰۲ است.
GET_USER_SQL = """
SELECT user_id, username, first_name, last_name, language_code,
       is_admin, first_seen_at, last_seen_at, message_count, last_action
FROM users
WHERE user_id = ?
""".strip()

# اگر ستون last_action هنوز ساخته نشده باشد، همین پرس‌وجو نام را برمی‌گرداند
# و موضوع آخرین کار خالی می‌ماند. تاریخچهٔ ساختگی ساخته نمی‌شود.
GET_USER_SQL_LEGACY = """
SELECT user_id, username, first_name, last_name, language_code,
       is_admin, first_seen_at, last_seen_at, message_count
FROM users
WHERE user_id = ?
""".strip()

# فقط آخرین کار عوض می‌شود. شمارنده و first_seen_at این‌جا دست نمی‌خورند
# چون خود touch آن‌ها را موقع هر آپدیت به‌روز کرده است.
SET_LAST_ACTION_SQL = "UPDATE users SET last_action = ? WHERE user_id = ?"

# کدهای مجاز. هر چیز دیگر در ستون نمی‌نشیند تا خوش‌آمد جملهٔ ناشناس نسازد.
LAST_ACTIONS = frozenset({"sample", "sheba", "faq", "excel"})


def utc_now_iso() -> str:
    """زمان فعلی UTC به شکل ISO، بدون کسری ثانیه. متن است چون ستون جدول TEXT است."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class UserProfile:
    """یک ردیف کاربر، مستقل از این‌که از حافظه آمده یا از D1."""

    user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    is_admin: bool
    first_seen_at: str
    last_seen_at: str
    message_count: int
    # None یعنی هنوز کاری ثبت نشده یا ستون مهاجرت نشده است.
    last_action: str | None = None


class UserStore(Protocol):
    """قرارداد مشترک حافظهٔ تست و D1 واقعی. بقیهٔ بازو فقط همین را می‌بیند."""

    async def touch(self, profile: UserProfile) -> None:
        """کاربر را بساز یا اگر هست به‌روز کن و شمارنده را یکی زیاد کن."""

    async def list_recent(self, limit: int = RECENT_USER_LIMIT) -> list[UserProfile]:
        """آخرین بازدیدکننده‌ها، تازه‌ترین نفر اول."""

    async def get(self, user_id: int) -> UserProfile | None:
        """یک کاربر را برای خوش‌آمد می‌خواند. نبودن ردیف یعنی None، نه خطا."""

    async def set_last_action(self, user_id: int, action: str) -> None:
        """آخرین کار را ذخیره می‌کند. کد ناشناس و کاربر غایب عمداً نادیده گرفته می‌شوند."""


def _coerce_user_id(value: object) -> int | None:
    # bool زیرکلاس int است؛ True را شناسهٔ کاربر حساب نمی‌کنیم.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
    else:
        return None
    if number <= 0:
        return None
    return number


def _optional_text(value: object, limit: int) -> str | None:
    """متن خالی را NULL می‌کنیم تا ستون به‌جای رشتهٔ بی‌معنی خالی بماند."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:limit]


def _as_bool_flag(value: object) -> bool:
    # مقدار ستون is_admin عدد است. رشتهٔ «0» نباید مدیر حساب شود.
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False


def _coerce_count(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def profile_from_bale_user(user: object, *, is_admin: bool, seen_at: str) -> UserProfile | None:
    """فیلدهای شیء from بله را به ردیف جدول تبدیل می‌کند. شناسهٔ نامعتبر یعنی ذخیره نکن."""
    if not isinstance(user, dict):
        return None
    user_id = _coerce_user_id(user.get("id"))
    if user_id is None:
        return None
    return UserProfile(
        user_id=user_id,
        username=_optional_text(user.get("username"), 64),
        first_name=_optional_text(user.get("first_name"), 128),
        last_name=_optional_text(user.get("last_name"), 128),
        language_code=_optional_text(user.get("language_code"), 16),
        is_admin=is_admin,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
        message_count=0,
        last_action=None,
    )


def bale_user_from_update(update: object) -> dict | None:
    """کاربر فرستنده را از callback یا message برمی‌گرداند.

    آپدیت بله یا پیام است یا callback. شناسه را از from همان بخش می‌گیریم،
    نه از chat، تا در گروه شناسهٔ گفتگو به‌جای آدم ذخیره نشود.
    """
    if not isinstance(update, dict):
        return None
    for key in ("callback_query", "message"):
        node = update.get(key)
        if isinstance(node, dict) and isinstance(node.get("from"), dict):
            return node["from"]
    return None


def display_name(profile: UserProfile) -> str:
    """نام قابل‌خواندن برای فهرست مدیر: نام، و اگر باشد نام کاربری با @."""
    parts = [part for part in (profile.first_name, profile.last_name) if part]
    name = " ".join(parts)
    if profile.username:
        handle = f"@{profile.username}"
        return f"{name} ({handle})" if name else handle
    return name or str(profile.user_id)


def format_recent_users(profiles: list[UserProfile]) -> str:
    """متن فارسی فهرست /users. اگر کسی نباشد، به‌جای جدول خالی یک جمله برمی‌گردد."""
    if not profiles:
        return "هنوز کاربری در پایگاه ثبت نشده است."
    lines = [f"کاربران اخیر ({len(profiles)} نفر):", ""]
    for index, profile in enumerate(profiles, start=1):
        role = "بله" if profile.is_admin else "خیر"
        lines.append(
            f"{index}. {display_name(profile)}\n"
            f"شناسه: {profile.user_id} | پیام: {profile.message_count} | "
            f"آخرین بازدید: {profile.last_seen_at} | مدیر: {role}"
        )
    return "\n".join(lines)


class MemoryUserStore:
    """همان قانون upsert، داخل یک دیکشنری. برای تست است، نه برای ورکر."""

    def __init__(self) -> None:
        self.by_id: dict[int, UserProfile] = {}

    async def touch(self, profile: UserProfile) -> None:
        current = self.by_id.get(profile.user_id)
        if current is None:
            self.by_id[profile.user_id] = replace(profile, message_count=1)
            return
        # اولین بازدید و آخرین کار می‌مانند. touch از روی پیام بله ساخته می‌شود
        # و last_action را ندارد؛ اگر این‌جا کپی شود، موضوع قبلی پاک می‌شود.
        self.by_id[profile.user_id] = replace(
            profile,
            first_seen_at=current.first_seen_at,
            message_count=current.message_count + 1,
            last_action=current.last_action,
        )

    async def get(self, user_id: int) -> UserProfile | None:
        return self.by_id.get(user_id)

    async def set_last_action(self, user_id: int, action: str) -> None:
        if action not in LAST_ACTIONS:
            return
        current = self.by_id.get(user_id)
        if current is None:
            return
        self.by_id[user_id] = replace(current, last_action=action)

    async def list_recent(self, limit: int = RECENT_USER_LIMIT) -> list[UserProfile]:
        ordered = sorted(
            self.by_id.values(),
            key=lambda row: (row.last_seen_at, row.user_id),
            reverse=True,
        )
        return ordered[: max(0, limit)]


def _known_action(value: object) -> str | None:
    """فقط کدهای شناخته‌شده برمی‌گردند. مقدار غریبه مثل نبودن موضوع است."""
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned in LAST_ACTIONS:
        return cleaned
    return None


def _as_py(value: object) -> object:
    """نتیجهٔ D1 در ورکر پایتون اغلب شیء جاوااسکریپت است.

    متد to_py آن را به dict و list پایتون تبدیل می‌کند. اگر از قبل پایتونی باشد
    همان را برمی‌گردانیم.
    """
    if value is None or isinstance(value, (str, int, float, bool, dict, list)):
        return value
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        try:
            return to_py()
        except Exception:
            return value
    return value


def _result_rows(result: object) -> list[dict]:
    """ردیف‌های آرایهٔ results را از جواب prepare().all() یا run() بیرون می‌کشد."""
    data = _as_py(result)
    if isinstance(data, dict):
        raw_rows = data.get("results") or []
    else:
        raw_rows = getattr(result, "results", None)
    raw_rows = _as_py(raw_rows)
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict] = []
    for item in raw_rows:
        item = _as_py(item)
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _profile_from_row(row: dict) -> UserProfile | None:
    user_id = _coerce_user_id(row.get("user_id"))
    if user_id is None:
        return None
    return UserProfile(
        user_id=user_id,
        username=_optional_text(row.get("username"), 64),
        first_name=_optional_text(row.get("first_name"), 128),
        last_name=_optional_text(row.get("last_name"), 128),
        language_code=_optional_text(row.get("language_code"), 16),
        is_admin=_as_bool_flag(row.get("is_admin")),
        first_seen_at=str(row.get("first_seen_at") or ""),
        last_seen_at=str(row.get("last_seen_at") or ""),
        message_count=_coerce_count(row.get("message_count")),
        last_action=_known_action(row.get("last_action")),
    )


class D1UserStore:
    """پیاده‌سازی واقعی روی باندینگ DB.

    prepare کوئری را آماده می‌کند، bind مقدارها را به‌جای علامت سؤال می‌گذارد
    (تا متن کاربر وارد خود SQL نشود)، run برای نوشتن است و all برای خواندن چند ردیف.
    مقدار None در پایتون به NULL در SQLite می‌رسد.
    """

    def __init__(self, db: object) -> None:
        self.db = db

    async def touch(self, profile: UserProfile) -> None:
        statement = self.db.prepare(UPSERT_SQL).bind(  # type: ignore[attr-defined]
            profile.user_id,
            profile.username,
            profile.first_name,
            profile.last_name,
            profile.language_code,
            1 if profile.is_admin else 0,
            profile.first_seen_at,
            profile.last_seen_at,
        )
        await statement.run()

    async def get(self, user_id: int) -> UserProfile | None:
        try:
            rows = await self._fetch(GET_USER_SQL, int(user_id))
        except Exception:
            # ستون last_action هنوز نیست. نام و شمارنده را از جدول قبلی می‌خوانیم.
            rows = await self._fetch(GET_USER_SQL_LEGACY, int(user_id))
        if not rows:
            return None
        return _profile_from_row(rows[0])

    async def set_last_action(self, user_id: int, action: str) -> None:
        if action not in LAST_ACTIONS:
            return
        statement = self.db.prepare(SET_LAST_ACTION_SQL).bind(action, int(user_id))  # type: ignore[attr-defined]
        await statement.run()

    async def _fetch(self, sql: str, user_id: int) -> list[dict]:
        statement = self.db.prepare(sql).bind(user_id)  # type: ignore[attr-defined]
        result = await statement.all()
        return _result_rows(result)

    async def list_recent(self, limit: int = RECENT_USER_LIMIT) -> list[UserProfile]:
        statement = self.db.prepare(LIST_RECENT_SQL).bind(int(limit))  # type: ignore[attr-defined]
        # all و run هر دو results را برمی‌گردانند. all را این‌جا صدا می‌زنیم
        # چون قصد، خواندن چند ردیف است نه درج.
        result = await statement.all()
        profiles: list[UserProfile] = []
        for row in _result_rows(result):
            profile = _profile_from_row(row)
            if profile is not None:
                profiles.append(profile)
        return profiles
