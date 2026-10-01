-- هر کار قابل‌شمارش یک ردیف است تا /stats بدون اسکن متن پیام‌ها جمع بزند.
-- kind فقط یکی از این‌هاست: excel (فایل متنی به مدیر رسید)، faq (باز شدن یک پاسخ)،
-- sheba (شروع اعتبارسنجی)، sample (ارسال موفق نمونه).
-- detail برای faq متن کوتاه پرسش است تا پرسش پرتکرار معلوم شود؛ برای بقیه خالی است.
-- created_at مثل last_seen_at به وقت UTC و قالب ISO با پسوند Z است
-- تا مقایسهٔ متنی «از نیمه‌شب تهران تا نیمه‌شب بعد» درست بماند.
-- این فایل را خود ورکر اجرا نمی‌کند. wrangler هر مهاجرت را یک بار اعمال می‌کند.

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);

-- بازهٔ امروز روی created_at فیلتر می‌شود. این نمایه همان فیلتر را ارزان‌تر می‌کند.
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at);
CREATE INDEX IF NOT EXISTS idx_events_kind_created ON events (kind, created_at);
