-- سپرده‌های مشتری. یکی از آن‌ها مبدأ واریز گروهی است (is_active = 1).
-- sheba فقط شبای معتبر بانک مهر (کد ۰۶۰) است و یکتایی‌اش برای هر کاربر است.
-- label برچسب اختیاری است، مثل «حقوق». خالی یعنی فقط شبا نشان داده شود.
-- حذف سپردهٔ فعال در کد، سپردهٔ بعدی را فعال می‌کند تا دو مبدأ هم‌زمان نماند.
-- این فایل را خود ورکر اجرا نمی‌کند.

CREATE TABLE IF NOT EXISTS deposits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  sheba TEXT NOT NULL,
  label TEXT,
  is_active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, sheba)
);

CREATE INDEX IF NOT EXISTS idx_deposits_user ON deposits (user_id);
