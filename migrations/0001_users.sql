-- جدول کاربران بازوی بله.
-- هر آدم یک ردیف دارد. شناسهٔ بله کلید اصلی است، پس دیدار دوباره ردیف تازه نمی‌سازد
-- و همان ردیف به‌روز می‌شود (upsert).
-- این فایل را خود ورکر اجرا نمی‌کند. با دستور مهاجرت wrangler روی دیتابیس D1 اعمال می‌شود.

CREATE TABLE IF NOT EXISTS users (
  -- شناسهٔ عددی کاربر در بله. همان عددی که دستور /id نشان می‌دهد.
  user_id INTEGER PRIMARY KEY,
  -- نام کاربری بدون علامت @. اگر کاربر نام کاربری نداشته باشد خالی می‌ماند.
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  -- زبان برنامهٔ بله، اگر در آپدیت آمده باشد (مثلاً fa).
  language_code TEXT,
  -- ۱ یعنی آخرین بار این شناسه با ADMIN_ID یکی بوده است. ۰ یعنی کاربر عادی.
  is_admin INTEGER NOT NULL DEFAULT 0,
  -- اولین باری که این کاربر را دیدیم، به وقت UTC و قالب ISO.
  -- در به‌روزرسانی‌های بعدی عمداً دست نمی‌خورد.
  first_seen_at TEXT NOT NULL,
  -- زمان آخرین پیام یا کلیک. هر بار تازه می‌شود.
  last_seen_at TEXT NOT NULL,
  -- تعداد آپدیت‌های یکتا. پیش‌فرض ۰ است؛ درج از کد با ۱ شروع می‌کند.
  message_count INTEGER NOT NULL DEFAULT 0
);

-- دستور /users آخرین بازدیدها را تازه به کهنه نشان می‌دهد. این نمایه همان مرتب‌سازی را ارزان‌تر می‌کند.
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users (last_seen_at);
