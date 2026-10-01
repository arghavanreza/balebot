"""ثبت کاربر: حافظهٔ تست، شکل کوئری D1، و دستور /users.

پایگاه واقعی این‌جا ساخته نمی‌شود. MemoryUserStore همان قانون upsert را دارد
و یک باندینگ ساختگی بررسی می‌کند که D1UserStore پارامترها را درست می‌فرستد.
"""

import asyncio

from users import (
    GET_USER_SQL_LEGACY,
    SET_LAST_ACTION_SQL,
    UPSERT_SQL,
    D1UserStore,
    MemoryUserStore,
    UserProfile,
    bale_user_from_update,
    format_recent_users,
    profile_from_bale_user,
)


def _run(coro):
    return asyncio.run(coro)


def _profile(user_id: int, seen: str, *, username: str | None = None, is_admin: bool = False) -> UserProfile:
    return UserProfile(
        user_id=user_id,
        username=username,
        first_name="علی",
        last_name=None,
        language_code="fa",
        is_admin=is_admin,
        first_seen_at=seen,
        last_seen_at=seen,
        message_count=0,
    )


def test_upsert_sql_keeps_first_seen_and_increments_count():
    update_clause = UPSERT_SQL.split("DO UPDATE SET", 1)[1]
    assert "first_seen_at" not in update_clause
    assert "message_count = users.message_count + 1" in update_clause
    assert "ON CONFLICT(user_id)" in UPSERT_SQL


def test_memory_store_preserves_first_seen_and_sorts_recent_first():
    async def scenario():
        store = MemoryUserStore()
        await store.touch(_profile(7, "2026-10-01T00:00:00Z", username="ali"))
        await store.touch(_profile(8, "2026-10-01T01:00:00Z"))
        await store.touch(_profile(7, "2026-10-01T02:00:00Z", username="ali2", is_admin=True))

        saved = store.by_id[7]
        assert saved.first_seen_at == "2026-10-01T00:00:00Z"
        assert saved.last_seen_at == "2026-10-01T02:00:00Z"
        assert saved.message_count == 2
        assert saved.username == "ali2"
        assert saved.is_admin is True
        assert [row.user_id for row in await store.list_recent(10)] == [7, 8]
        assert len(await store.list_recent(1)) == 1

    _run(scenario())


def test_last_action_survives_touch_and_unknown_codes_are_ignored():
    async def scenario():
        store = MemoryUserStore()
        await store.touch(_profile(7, "2026-10-01T00:00:00Z"))
        await store.set_last_action(7, "sheba")
        await store.set_last_action(7, "invented")
        await store.touch(_profile(7, "2026-10-01T02:00:00Z", username="ali2"))
        saved = await store.get(7)
        assert saved is not None
        assert saved.last_action == "sheba"
        assert saved.message_count == 2
        assert saved.username == "ali2"
        assert await store.get(99) is None
        await store.set_last_action(99, "faq")

    _run(scenario())


def test_profile_from_bale_user_rejects_bad_ids_and_blank_text():
    seen = "2026-10-01T00:00:00Z"
    profile = profile_from_bale_user(
        {"id": "7", "username": "  ", "first_name": "علی", "language_code": "fa"},
        is_admin=False,
        seen_at=seen,
    )
    assert profile is not None
    assert profile.user_id == 7
    assert profile.username is None
    assert profile.language_code == "fa"
    assert profile_from_bale_user({"id": True}, is_admin=False, seen_at=seen) is None
    assert profile_from_bale_user({"id": 0}, is_admin=False, seen_at=seen) is None
    assert bale_user_from_update({"callback_query": {"from": {"id": 3}}}) == {"id": 3}
    assert bale_user_from_update({"message": {"chat": {"id": 3}}}) is None


def test_format_recent_users_is_persian():
    text = format_recent_users([_profile(7, "2026-10-01T00:00:00Z", username="ali")])
    assert "کاربران اخیر" in text
    assert "@ali" in text
    assert "شناسه: 7" in text
    assert format_recent_users([]) == "هنوز کاربری در پایگاه ثبت نشده است."


class _JsResult:
    """شکل جواب D1 در ورکر پایتون: شیئی که to_py دیکشنری برمی‌گرداند."""

    def __init__(self, payload: dict):
        self._payload = payload

    def to_py(self):
        return self._payload


class _Stmt:
    def __init__(self, log: list, sql: str, rows: list):
        self.log = log
        self.sql = sql
        self.params = ()
        self._rows = rows

    def bind(self, *params):
        self.params = params
        return self

    async def run(self):
        self.log.append(("run", self.sql, self.params))
        return {"success": True, "results": []}

    async def all(self):
        self.log.append(("all", self.sql, self.params))
        return _JsResult({"success": True, "results": list(self._rows)})


class _DB:
    def __init__(self, rows: list):
        self.log: list = []
        self.rows = rows

    def prepare(self, sql: str) -> _Stmt:
        return _Stmt(self.log, sql, self.rows)


def test_d1_store_binds_upsert_and_reads_rows():
    async def scenario():
        db = _DB(
            [
                {
                    "user_id": 7,
                    "username": "ali",
                    "first_name": "علی",
                    "last_name": None,
                    "language_code": "fa",
                    "is_admin": 0,
                    "first_seen_at": "2026-10-01T00:00:00Z",
                    "last_seen_at": "2026-10-01T00:00:00Z",
                    "message_count": 3,
                }
            ]
        )
        store = D1UserStore(db)
        await store.touch(_profile(7, "2026-10-01T03:00:00Z", username="ali"))
        kind, sql, params = db.log[0]
        assert kind == "run"
        assert sql == UPSERT_SQL
        assert params[0] == 7
        assert params[1] == "ali"
        assert params[5] == 0
        assert params[6] == "2026-10-01T03:00:00Z"
        assert params[7] == "2026-10-01T03:00:00Z"

        rows = await store.list_recent(5)
        assert db.log[1][0] == "all"
        assert db.log[1][2] == (5,)
        assert rows[0].message_count == 3
        assert rows[0].username == "ali"
        assert rows[0].is_admin is False

        found = await store.get(7)
        assert found is not None
        assert found.message_count == 3
        assert found.last_action is None
        await store.set_last_action(7, "excel")
        await store.set_last_action(7, "nope")
        assert db.log[-1] == ("run", SET_LAST_ACTION_SQL, ("excel", 7))

    _run(scenario())


def test_d1_get_falls_back_when_last_action_column_is_missing():
    """مهاجرت ۰۰۰۲ نرفته باشد: نام می‌ماند و موضوع ساخته نمی‌شود."""

    class _LegacyStmt(_Stmt):
        async def all(self):
            self.log.append(("all", self.sql, self.params))
            if "last_action" in self.sql:
                raise RuntimeError("no such column: last_action")
            return _JsResult({"success": True, "results": list(self._rows)})

    class _LegacyDB(_DB):
        def prepare(self, sql: str) -> _LegacyStmt:
            return _LegacyStmt(self.log, sql, self.rows)

    async def scenario():
        db = _LegacyDB(
            [
                {
                    "user_id": 7,
                    "username": None,
                    "first_name": "علی",
                    "last_name": None,
                    "language_code": "fa",
                    "is_admin": 0,
                    "first_seen_at": "2026-10-01T00:00:00Z",
                    "last_seen_at": "2026-10-01T00:00:00Z",
                    "message_count": 4,
                }
            ]
        )
        profile = await D1UserStore(db).get(7)
        assert profile is not None
        assert profile.first_name == "علی"
        assert profile.message_count == 4
        assert profile.last_action is None
        selects = [sql for kind, sql, _params in db.log if kind == "all"]
        assert any("last_action" in sql for sql in selects)
        assert GET_USER_SQL_LEGACY in selects

    _run(scenario())

