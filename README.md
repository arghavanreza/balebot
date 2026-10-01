# بازوی بله — تبدیل اکسل / Bale Excel bot
Persian Bale bot on a **Python Cloudflare Worker** for Bank Mehr branch customers. A customer sends an `.xlsx` payroll file; the Worker turns the first sheet into a UTF-8 text file and sends that file to the admin (not back to the customer). The same bot hands out a sample workbook, checks an Iranian Sheba (IBAN), and answers a short branch FAQ. Every customer-facing string is stored in Workers KV and can be edited from the admin menu.

مستندات API بله: <https://docs.bale.ai/>

---

## فارسی

### این بازو چه می‌کند

- دریافت فایل `.xlsx`، تبدیل شیت اول به متن جداشده با تب، و ارسال همان فایل متنی برای `ADMIN_ID`.
- دکمهٔ «نمونه فایل برای واریز حقوق»: ارسال `assets/sample.xlsx` برای خود کاربر.
- پیش از آپلود، منو یک جمله نشان می‌دهد: چه فایل اکسلی بفرستند، اینکه خودشان تأیید می‌گیرند، و اینکه فایل متنی برای مدیر شعبه می‌رود. جمله در کلید `excel_upload_hint` است.
- دکمهٔ «اعتبارسنجی شبا»: دریافت شماره شبا و پاسخ معتبر / نامعتبر (IR به‌علاوهٔ ۲۴ رقم، الگوریتم ISO 7064 mod-97).
- دکمهٔ «پرسش‌های متداول»: چند پرسش شعبه. مشتری شماره یا دکمه را می‌زند و پاسخ را می‌بیند.
- اگر شناسهٔ فرستنده با `ADMIN_ID` یکی باشد، منوی مدیر نشان داده می‌شود و متن‌ها و پرسش‌ها از همان‌جا قابل ویرایش‌اند.
- `/start` اگر پایگاه کاربران در دسترس باشد، بار اول با نام سلام می‌کند و بار بعد «خوش برگشتی» می‌گوید. اگر D1 نباشد همان خوش‌آمد عمومی است.
- اگر مشتری هنوز شماره نداده باشد، بعد از خوش‌آمد شمارهٔ موبایل پرسیده می‌شود (دکمهٔ `request_contact` بله، یا تایپ `09…` / `+98…`). شماره در ستون `users.phone` می‌ماند. اگر از قبل باشد، دوباره پرسیده نمی‌شود.
- هر کاربری که پیام یا callback بفرستد در پایگاه D1 ثبت یا به‌روز می‌شود. مدیر با `/users` تازه‌ترین‌ها را می‌بیند و با `/stats` آمار امروز به وقت تهران را.
- با هر فایل اکسل، علاوه بر خود فایل متنی، یک خلاصه برای مدیر می‌رود: شناسه، زمان تهران، نام، نام کاربری، موبایل (اگر ثبت شده باشد) و تعداد سطر.
- `GET /health` سلامت ورکر را برمی‌گرداند. `POST /webhook` آپدیت بله را می‌گیرد.

قالب خروجی اکسل عمداً موقت است. نقطهٔ تغییر: تابع `convert_excel_to_text` در `src/excel_convert.py`.

### پیش‌نیاز

- Python 3.12 یا جدیدتر
- [uv](https://docs.astral.sh/uv/)
- Node.js (ابزار `pywrangler` / Wrangler)
- حساب Cloudflare و یک بازو در بله

### ۱. ساخت بازو و گرفتن توکن

1. در بله گفتگو با `@BotFather` را باز کنید.
2. `/newbot` را بفرستید و نام و نام کاربری بازو را وارد کنید.
3. توکن را فقط به‌صورت secret نگه دارید. آن را در گیت، README، یا `wrangler.jsonc` ننویسید.

### ۲. نصب

```bash
uv sync
```

### ۳. ساخت KV

باندینگ در `wrangler.jsonc` با نام `TEXTS` تعریف شده و شناسه‌اش فعلاً جای‌نگهدار است. قبل از deploy عوضش کنید:

```bash
npx wrangler kv namespace create TEXTS
```

خروجی یک `id` است. همان را در `wrangler.jsonc` داخل `kv_namespaces` به‌جای `00000000000000000000000000000001` بگذارید. برای توسعهٔ محلی همان جای‌نگهدار کافی است؛ Wrangler یک KV محلی می‌سازد.

متن‌ها در کلید `bot_texts` ذخیره می‌شوند. بار اول که خوانده شوند، پیش‌فرض‌های `src/texts.py` در KV نوشته می‌شود. کلید تازه‌ای که در نسخهٔ بعدی کد اضافه شود، بدون پاک کردن ویرایش‌های قبلی پر می‌شود.

وضعیت گفتگو (`state:<user id>`) و شناسهٔ آپدیت تکراری (`update:<id>`) هم در همین namespace هستند و TTL دارند (۳۰ دقیقه برای جریان، یک ساعت برای جلوگیری از پردازش دوباره).

### ۳٫۵ پایگاه کاربران (D1)، از جمله برای ورکر از قبل مستقر

کاربران در KV نیستند. D1 یک پایگاه SQLite کنار ورکر است. جدول `users` در `migrations/0001_users.sql` است و کد با باندینگ `DB` به آن وصل می‌شود.

شناسهٔ داخل `wrangler.jsonc` جای‌نگهدار است (`00000000-0000-4000-8000-000000000000`) و متعلق به هیچ حساب کلادفلری نیست. آن را حدس نزنید. بعد از دستور ساخت، همان `database_id` چاپ‌شده را در فایل بگذارید. این شناسه مثل توکن بازو راز نیست (شناسهٔ KV هم در همین فایل است) ولی تا وقتی پایگاه را نساخته‌اید نباید چیز دیگری جایش نوشته شود.

اگر ورکر همین حالا روی کلادفلر روشن است، این ترتیب را بروید. ساخت پایگاه و مهاجرت، نسخهٔ در حال اجرا را عوض نمی‌کند. نسخهٔ جدید وقتی کاربران را می‌نویسد که هم جدول ساخته شده باشد و هم ورکر دوباره با باندینگ `DB` منتشر شده باشد.

```bash
npx wrangler d1 create bale-bot-users
```

خروجی یک `database_id` دارد. همان را در `wrangler.jsonc` داخل `d1_databases` جایگزین جای‌نگهدار کنید. `database_name` باید `bale-bot-users` بماند تا با دستورهای زیر یکی باشد. نام باندینگ `DB` است و کد پایتون همین نام را می‌خواند.

برای `pywrangler dev` همان جای‌نگهدار کافی است. مهاجرت محلی یک فایل SQLite روی همین دستگاه می‌سازد و به حساب کلادفلر وصل نمی‌شود. شناسهٔ واقعی فقط برای پایگاه راه‌دور لازم است.

سپس جدول را روی پایگاه راه‌دور بسازید:

```bash
npx wrangler d1 migrations apply bale-bot-users --remote
```

این دستور فایل‌های `migrations/` را به ترتیب اجرا می‌کند و یادش می‌ماند کدام فایل اعمال شده، پس دوباره زدنش بی‌خطر است. بعد ورکر را منتشر کنید تا باندینگ به نسخهٔ در حال اجرا برسد:

```bash
uv run pywrangler deploy
```

اگر برعکس عمل کنید (اول deploy، بعد مهاجرت) بازو همچنان جواب می‌دهد و فقط تا ساخته شدن جدول، ثبت کاربر در لاگ خطا می‌دهد. هم وب‌هوک و هم زمان‌بند دقیقه‌ای از یک تابع می‌گذرند، پس کاربر در هر دو ذخیره می‌شود. آپدیت تکراری یک بار شمرده می‌شود.

برای `pywrangler dev` جدول محلی جداست:

```bash
npx wrangler d1 migrations apply bale-bot-users --local
```

مهاجرت `migrations/0002_last_action.sql` ستون `last_action` را اضافه می‌کند. این ستون فقط آخرین کار بازو است (`sample`، `sheba`، `faq`، `excel`) تا جملهٔ «خوش برگشتی» موضوع واقعی را بگوید. اگر هنوز اعمال نشده باشد، خوش‌آمد با نام کار می‌کند و موضوعی ساخته نمی‌شود. ثبت شمارهٔ موبایل این ستون را عوض نمی‌کند.

مهاجرت `migrations/0003_phone.sql` ستون `phone` را اضافه می‌کند (`TEXT`، تهی مجاز). مقدار ذخیره‌شده به شکل `+989` و ده رقم است. تا وقتی این ستون نباشد، خوش‌آمد و بقیهٔ بازو کار می‌کنند و فقط ذخیرهٔ شماره خطا می‌دهد.

مهاجرت `migrations/0004_events.sql` جدول `events` را می‌سازد: `user_id`، `kind` (`excel` / `faq` / `sheba` / `sample`)، `detail` (برای پرسش، متن کوتاه سؤال) و `created_at` به وقت UTC. دستور `/stats` از همین جدول و از `first_seen_at` / `last_seen_at` می‌خواند. اگر جدول نباشد، شمارش کاربران امروز همچنان می‌آید و شمارش رویدادها یک جملهٔ راهنما است.

بعد از گرفتن این نسخه، همان دستور مهاجرت را یک بار دیگر بزنید؛ فایل‌های قبلی دوباره اجرا نمی‌شوند.

دستور مدیر `/users` حداکثر ۲۰ نفر را به ترتیب آخرین بازدید نشان می‌دهد. `/stats` فقط برای مدیر است و امروز را به وقت تهران (UTC+03:30، بدون ساعت تابستانی) تعریف می‌کند: کاربر فعال یعنی `last_seen_at` در آن روز، کاربر تازه‌وارد یعنی `first_seen_at` در همان روز، و رویدادها با `created_at` در همان بازه. کاربر عادی همان پاسخ «فقط برای مدیر» را می‌گیرد. این دو دستور دکمهٔ کیبورد نیستند.

### ۴. Secrets

نام‌ها در `.env.example` هستند. مقدار واقعی را commit نکنید.

محلی (Wrangler فایل `.dev.vars` را می‌خواند، نه `.env`):

```bash
cp .env.example .dev.vars
```

سپس این سه مقدار را پر کنید:

| نام | معنی |
| --- | --- |
| `BALE_TOKEN` | توکن BotFather |
| `ADMIN_ID` | شناسهٔ عددی مدیر، به‌صورت رشته (مثلاً `123456789`) |
| `WEBHOOK_SECRET` | اختیاری. اگر خالی باشد فقط مسیر `/webhook` باز است |

`DRY_RUN=1` در `.dev.vars` تماس با بله را قطع می‌کند و عمل‌هایی که انجام می‌شد را در پاسخ HTTP برمی‌گرداند. فقط برای توسعهٔ محلی است؛ در production نگذارید.

روی Cloudflare:

```bash
uv run pywrangler secret put BALE_TOKEN
uv run pywrangler secret put ADMIN_ID
uv run pywrangler secret put WEBHOOK_SECRET   # اختیاری
```

`secret put` خودش نسخهٔ جدید ورکر را منتشر می‌کند. این مقادیر را داخل `[vars]` در فایل تنظیمات نگذارید.

### ۵. اجرای محلی

```bash
uv run pywrangler dev --port 43123
```

- سلامت: `GET http://127.0.0.1:43123/health`
- وب‌هوک: `POST http://127.0.0.1:43123/webhook`

بله فقط به آدرس HTTPS روی پورت ۴۴۳ یا ۸۸ آپدیت می‌فرستد. برای تست واقعی از روی لپ‌تاپ یک تونل HTTPS (مثل cloudflared) لازم است. بدون تونل، منطق بازو را با `DRY_RUN=1` و `pytest` می‌توان دید.

تست‌ها (بدون شبکه و بدون توکن):

```bash
uv run pytest
```

نمونهٔ اکسل را دوباره بسازید:

```bash
uv run python scripts/make_sample.py
```

### ۶. استقرار

```bash
uv run pywrangler deploy
```

آدرس ورکر در خروجی چاپ می‌شود، شبیه `https://bale-excel-bot.<subdomain>.workers.dev`. این آدرس پورت ۴۴۳ است و برای وب‌هوک بله مناسب است.

### ۷. ثبت وب‌هوک

اگر `WEBHOOK_SECRET` خالی است:

```bash
export BALE_TOKEN="توکن"
export WEBHOOK_URL="https://<worker>/webhook"
uv run python scripts/set_webhook.py
```

اگر secret تنظیم شده، همان مقدار باید در مسیر باشد (کاراکترهای URL-safe، بدون `/`):

```bash
export WEBHOOK_URL="https://<worker>/webhook/<WEBHOOK_SECRET>"
uv run python scripts/set_webhook.py
```

معادل با curl:

```bash
curl --request POST \
  "https://tapi.bale.ai/bot${BALE_TOKEN}/setWebhook" \
  --header "Content-Type: application/json" \
  --data "{\"url\":\"${WEBHOOK_URL}\"}"
```

وقتی secret روشن است، درخواست به `/webhook` بدون سگمنت باید هدر `X-Webhook-Secret` را هم داشته باشد. بله این هدر را نمی‌فرستد؛ در عمل آدرس را با سگمنت secret ثبت کنید.

مسیر کمکی روی خود ورکر (فقط وقتی `WEBHOOK_SECRET` تنظیم شده باشد):

```bash
curl --request POST "https://<worker>/set-webhook" \
  --header "Content-Type: application/json" \
  --header "X-Setup-Secret: ${WEBHOOK_SECRET}" \
  --data "{\"url\":\"https://<worker>/webhook/${WEBHOOK_SECRET}\"}"
```

برای خاموش کردن وب‌هوک، `url` را رشتهٔ خالی بگذارید (طبق مستند `setWebhook`).

### ۸. پیدا کردن شناسهٔ مدیر

1. وب‌هوک را وصل کنید (حتی قبل از اینکه `ADMIN_ID` درست باشد بازو برای کاربران عادی کار می‌کند).
2. به بازو `/id` بفرستید. پاسخ، شناسهٔ عددی شماست.
3. همان عدد را بگذارید:

```bash
uv run pywrangler secret put ADMIN_ID
```

شناسه در لاگ ورکر هم هنگام `/start` و `/id` چاپ می‌شود: `uv run pywrangler tail`.

بعد از این، `/start` برای آن شناسه منوی مدیر را نشان می‌دهد و برای بقیه خوش‌آمد و دکمه‌های کاربر (نمونهٔ حقوق، اعتبارسنجی شبا، پرسش‌های متداول) را.

### ۹. ویرایش متن‌ها (مدیر)

1. `/start`
2. «ویرایش متن»
3. شماره یا نام کلید را بفرستید (مثلاً `1` یا `welcome`)
4. متن جدید را در پیام بعدی بفرستید
5. «انصراف»، «بازگشت»، `/cancel` یا `/start` جریان را قطع می‌کند

کلیدها و متن پیش‌فرض در `src/texts.py` هستند. برچسب دکمه‌ها هم کلیدند (`btn_sample`، `btn_sheba`، `btn_faq`، `btn_faq_edit`، `btn_faq_back`، `btn_edit`، `btn_back`، `btn_cancel`). بعد از ذخیره، کیبورد بعدی برچسب جدید را نشان می‌دهد. برچسب‌ها را تکراری نگذارید.

جملهٔ پیش از ارسال فایل حقوق کلید `excel_upload_hint` است. اگر در KV هنوز عین پیش‌فرض نسخهٔ قبل مانده باشد (مثلاً دکمهٔ «دریافت سمپل اکسل» یا «بررسی شبا»)، بار بعد با پیش‌فرض جدید عوض می‌شود. متنی که خودتان ذخیره کرده‌اید دست نمی‌خورد.

| کلید خوش‌آمد | کی دیده می‌شود | جای‌نگهدار |
| --- | --- | --- |
| `welcome` | پایگاه کاربر نیست، یا نامی در پرونده نیست و اولین بازدید است | — |
| `welcome_first` | اولین بازدید و `first_name` موجود است | `{name}` |
| `welcome_back` | بازگشت، با نام، بدون آخرین کار | `{name}` |
| `welcome_back_plain` | بازگشت، بدون نام و بدون آخرین کار | — |
| `welcome_back_topic` | بازگشت، با نام و آخرین کار واقعی | `{name}` `{topic}` |
| `welcome_back_topic_plain` | بازگشت، بدون نام، با آخرین کار | `{topic}` |
| `topic_excel` | نام آخرین کار وقتی فایل اکسل فرستاده شده | — |
| `excel_upload_hint` | ته منوی مشتری، پیش از آپلود | — |

`{topic}` از روی برچسب همان کار ساخته می‌شود (`btn_sample`، `btn_sheba`، `btn_faq`، یا `topic_excel`). اگر آخرین کاری ثبت نشده باشد این جمله اصلاً ساخته نمی‌شود.

جای‌نگهدارها فقط به شکل `{token}` جایگزین می‌شوند و نام ناشناس دست‌نخورده می‌ماند:

| کلید | جای‌نگهدار |
| --- | --- |
| `sheba_valid` / `sheba_invalid` | `{sheba}` |
| `excel_admin_caption` | `{user_label}` `{user_id}` `{timestamp}` `{phone}` `{filename}` `{rows}` |
| `excel_admin_summary` | `{user_id}` `{timestamp}` `{first_name}` `{last_name}` `{username}` `{phone}` `{rows}` `{chars}` `{filename}` |
| `phone_saved` | `{phone}` |
| `id_reply` | `{user_id}` |
| `admin_value_prompt` | `{key}` `{current}` |
| `admin_saved` | `{key}` |
| `welcome_first` / `welcome_back` | `{name}` |
| `welcome_back_topic` | `{name}` `{topic}` |
| `welcome_back_topic_plain` | `{topic}` |
| `faq_full` | `{max}` |
| `faq_ask_question` / `faq_ask_answer` | `{current}` |
| `faq_admin_bad` | `{add}` `{delete}` |

### ۹.۱ پرسش‌های متداول

پرسش و پاسخ‌ها در کلید KV جداگانه‌ای به نام `bot_faq` هستند، نه داخل `bot_texts`. سند این شکل را دارد:

```json
{
  "items": [
    {"id": "open-account", "question": "متن پرسش", "answer": "متن پاسخ"}
  ],
  "hidden": ["hours"]
}
```

`items` ترتیب نمایش است. `hidden` شناسهٔ پیش‌فرض‌هایی است که مدیر حذف کرده تا با استقرار بعدی دوباره برنگردند. پرسش تازه‌ای که فقط در کد اضافه شود و در `hidden` نباشد، ته فهرست قبلی اضافه می‌شود.

از منوی مدیر، بدون استقرار مجدد:

1. «ویرایش پرسش‌ها»
2. شمارهٔ ردیف را بفرستید، بعد متن پرسش، بعد متن پاسخ
3. `جدید` برای افزودن (حداکثر ۱۰ پرسش)
4. `حذف ۲` یا `حذف۲` برای حذف همان ردیف
5. «بازگشت»، «انصراف»، `/cancel` یا `/start` بیرون می‌آید

کلمهٔ افزودن کلید `faq_cmd_add` است و پیشوند حذف کلید `faq_cmd_delete`. اگر این دو را عوض کنید، راهنمای `faq_admin_prompt` را هم با همان کلمه‌ها هم‌خوان کنید.

شناسه‌های پیش‌فرض (متن‌ها نمونه‌اند و کارمزد و ساعت قطعی عمداً داخلشان ثابت نشده):

| id | موضوع |
| --- | --- |
| `open-account` | مدارک افتتاح حساب |
| `settlement` | زمان نشستن واریز حقوق |
| `fee` | کارمزد |
| `sheba-docs` | مدرک لازم برای شبا |
| `hours` | ساعت کار شعبه |
| `payroll-file` | نحوهٔ ارسال فایل حقوق |
| `trace` | اگر مبلغ ننشست |
| `limits` | سقف انتقال |

مشتری در منو «پرسش‌های متداول» را می‌زند، شماره یا دکمهٔ پرسش را انتخاب می‌کند، و با «بازگشت به پرسش‌ها» یا «بازگشت» برمی‌گردد. بیرون از این فهرست، فرستادن عدد تنها اولین پاسخ را باز نمی‌کند.

### ۹.۲ خوش‌آمد شخصی

فقط روی `/start` و فقط برای غیرمدیر. بازگشت از یک جریان، منوی معمولی را نشان می‌دهد تا «خوش برگشتی» وسط کار تکرار نشود.

- بار اول، اگر `first_name` در پرونده باشد: `welcome_first`
- بار بعد: «خوش برگشتی» به‌همراه نام
- اگر ستون `last_action` یکی از `sample` / `sheba` / `faq` / `excel` باشد، همان کار در جمله می‌آید
- مقدار خالی یا ناشناس یعنی موضوعی گفته نمی‌شود
- اگر نام در پرونده نباشد: اولین بار همان `welcome`، و بازگشت `welcome_back_plain`
- اگر D1 وصل نباشد یا `get` خطا بدهد: کلید `welcome`، و بازو خراب نمی‌شود
- اگر فقط ستون `last_action` هنوز نباشد: خوش‌آمد با نام می‌ماند و موضوعی ساخته نمی‌شود
- اگر مشتری مدیر نباشد و `phone` در پرونده خالی باشد، پیام بعدی شماره می‌خواهد. دکمهٔ اول `request_contact` بله است؛ تایپ `09…` یا `+98…` هم پذیرفته می‌شود. «انصراف» یا دکمه‌های منو گفتگو را بدون شماره ادامه می‌دهند. مدیر این پرسش را نمی‌بیند تا پنلش جابه‌جا نشود.

جملهٔ فایل حقوق (`excel_upload_hint`) و راهنمای دکمه‌ها (`welcome_hint`) زیر هر دو نوع خوش‌آمد می‌آیند.

بله متن را مارک‌داون می‌بیند: ستاره و زیرخط اطرافشان فاصله می‌خواهند. اگر نمی‌خواهید بخشی از پیام بولد شود، `*` و `_` را در متن ویرایش‌شده بی‌دلیل نگذارید.

سقف ذخیره حدود ۳۵۰۰ نویسه است (ارسال پیام در بله تا ۴۰۹۶ نویسه).

### ۱۰. سفارشی‌سازی تبدیل اکسل به متن

فایل `src/excel_convert.py`، تابع `convert_excel_to_text(data: bytes) -> str`.

رفتار فعلی، تا وقتی نگاشت ستون‌ها قطعی شود:

- فقط شیت اول
- هر سطر غیرخالی، خانه‌ها با تب، سطرها با خط جدید
- سطر عنوان هم هست
- UTF-8
- شیت‌های بعدی نادیده گرفته می‌شوند
- فرمول‌ها به‌صورت متن فرمول می‌آیند (`data_only=False`)، چون مقدار کش‌شده فقط اگر اکسل فایل را باز کرده باشد وجود دارد
- حداکثر ۵۰۰۰ سطر و ۵۰ ستون

امضای تابع را عوض نکنید. هندلر در `src/bot.py` فقط همین رشته را به فایل `.txt` تبدیل می‌کند و با `sendDocument` برای مدیر می‌فرستد. برای آزمایش یک مبدل دیگر، آرگومان `converter` روی `BotContext` را عوض کنید.

نمونهٔ خروجی پیش‌فرض:

```text
name	amount	sheba
علی رضایی	1500000	IR43...
```

### ۱۱. فایل نمونه

`assets/sample.xlsx` در مخزن است و با استقرار، به‌صورت static asset بالا می‌رود. ورکر آن را از باندینگ `ASSETS` می‌خواند (اگر نشد، از روی دیسک). ستون‌ها: `name`، `amount`، `sheba`. شباها از نظر رقم کنترلی معتبرند ولی شماره حساب واقعی نیستند. شیت دوم عمداً نادیده گرفته می‌شود.

جایگزین R2 (اختیاری). در `wrangler.jsonc` بلوک `r2_buckets` را از کامنت دربیاورید، بعد:

```bash
npx wrangler r2 bucket create bale-bot-files
npx wrangler r2 object put bale-bot-files/sample.xlsx --file assets/sample.xlsx
```

اگر باندینگ `FILES` وجود داشته باشد، کلید `sample.xlsx` بر asset اولویت دارد.

### ۱۲. قاعدهٔ شبا

ورودی‌های پذیرفته‌شده: `IR` به‌علاوهٔ ۲۴ رقم، با فاصله یا خط تیره، با ارقام فارسی یا عربی، و با پیشوند «شبا». بدون پیشوند `IR` نامعتبر است. رقم کنترلی با ISO 7064 mod-97 بررسی می‌شود (باقی‌مانده باید ۱ باشد).

نمونهٔ معتبر (جای‌نگهدار، نه حساب واقعی): `IR430120000000000000000001`  
نمونهٔ نامعتبر: `IR000000000000000000000000`

منطق خالص در `src/sheba.py` است (`validate_sheba`).

### دستورهای کاربر

| دستور یا دکمه | کار |
| --- | --- |
| `/start` | منوی کاربر یا مدیر؛ برای مشتریِ بدون شماره، درخواست موبایل هم می‌آید |
| `/id` | نمایش شناسهٔ عددی |
| `/users` | فقط مدیر: فهرست کاربران اخیر از D1 |
| `/stats` | فقط مدیر: آمار امروز به وقت تهران |
| `/cancel` | لغو جریان فعلی |
| نمونه فایل برای واریز حقوق | ارسال نمونه برای خود کاربر |
| اعتبارسنجی شبا | درخواست شبا؛ تا پاسخ معتبر یا انصراف در همین حالت می‌ماند |
| پرسش‌های متداول | فهرست پرسش شعبه؛ شماره یا دکمه پاسخ را باز می‌کند |
| ارسال `.xlsx` | تبدیل و ارسال برای مدیر، بعد تأیید برای فرستنده |

دانلود فایل از بله تا ۲۰ مگابایت است (`getFile`). فایل بزرگ‌تر رد می‌شود.

### اگر جایی گیر کرد

| پاسخ HTTP | معنی |
| --- | --- |
| 401 `unauthorized` | secret وب‌هوک نمی‌خواند |
| 500 `missing_token` | `BALE_TOKEN` نیست و `DRY_RUN` هم خاموش است |
| 500 `missing_kv_binding` | باندینگ `TEXTS` در wrangler نیست |
| 400 `bad_json` | بدنهٔ آپدیت JSON نیست |

کلاینت HTTP در `src/bale.py` است: `sendMessage`، `sendDocument` (multipart)، `getFile` به‌علاوهٔ دانلود از `https://tapi.bale.ai/file/bot<TOKEN>/<file_path>`، `answerCallbackQuery`، `setWebhook`.

---

## English

### What it does

- Accepts an `.xlsx` upload, converts the first sheet to tab-separated UTF-8 text, and sends that text file to `ADMIN_ID` with `sendDocument`. The sender only gets an acknowledgement.
- Reply-keyboard button «نمونه فایل برای واریز حقوق» sends `assets/sample.xlsx` so customers can see the expected columns (`name`, `amount`, `sheba`).
- Before an upload, the customer menu shows one sentence (`excel_upload_hint`): which `.xlsx` to send, that the sender gets an acknowledgement, and that the admin receives a text file.
- Reply-keyboard button «اعتبارسنجی شبا» asks for an Iranian IBAN and answers valid or invalid.
- Reply-keyboard button «پرسش‌های متداول» opens a short branch FAQ. A number or button shows the answer.
- When the sender’s numeric id equals `ADMIN_ID`, `/start` shows an admin menu that edits customer-facing strings and FAQ entries at runtime (Workers KV, not a redeploy).
- With D1 available, `/start` greets a first visit by `first_name` and a later visit with «خوش برگشتی», plus the last real action when one is stored. If D1 is down, the generic `welcome` text is used.
- After that greeting, a customer with no stored mobile is asked for one. The keyboard uses Bale `request_contact`; typed `09…` / `+98…` is accepted too. The number is stored on `users.phone`. A return visit that already has a phone skips the question.
- Every user who sends a message or callback is upserted into Cloudflare D1. The admin lists recent users with `/users` and today’s Tehran-time counts with `/stats`.
- An Excel upload still delivers the `.txt` file to the admin, and also a summary message: user id, Tehran timestamp (with the UTC instant), first and last name, username, phone from D1, and row count.
- `GET /health` → `{"ok": true}`. `POST /webhook` is the Bale webhook.

The Excel mapping is explicitly temporary. Change `convert_excel_to_text(data: bytes) -> str` in `src/excel_convert.py`. There is a TODO in that file.

### Requirements

Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js, a Cloudflare account, and a Bale bot token.

### 1. Create the bot

1. Open `@BotFather` in Bale.
2. Send `/newbot` and follow the prompts.
3. Store the token as a Worker secret. Do not commit it.

### 2. Install

```bash
uv sync
```

`openpyxl` parses `.xlsx` (pure Python, bundled by `pywrangler`). `httpx` performs the raw JSON and multipart calls to `https://tapi.bale.ai`. The `python_workers` compatibility flag is set in `wrangler.jsonc`.

### 3. Create the KV namespace

`wrangler.jsonc` binds `TEXTS` to a placeholder id so local dev works. Replace it before the first real deploy:

```bash
npx wrangler kv namespace create TEXTS
```

Paste the printed `id` over `00000000000000000000000000000001`.

On first read the Worker writes the defaults from `src/texts.py` under the key `bot_texts`. Later code that adds a key merges it in and keeps existing edits. Conversation state (`state:<user id>`, 30 minutes) and update de-dupe (`update:<id>`, 1 hour) use the same namespace. Durable Objects are not used.

### 3.5 User database (D1), including an already-deployed Worker

Users are stored in D1 (SQLite beside the Worker), not in KV. The table is `migrations/0001_users.sql`. The Worker reads it through the `DB` binding.

The `database_id` in `wrangler.jsonc` is a placeholder (`00000000-0000-4000-8000-000000000000`). It is not a real Cloudflare id. Replace it with the id printed by the create command. Do not invent one.

Creating the database and applying migrations does not change the Worker that is already running. The new code writes users only after the table exists and the Worker is redeployed with the `DB` binding.

```bash
npx wrangler d1 create bale-bot-users
```

Paste the printed `database_id` over the placeholder in `d1_databases`. Keep `database_name` as `bale-bot-users` and the binding name as `DB` (the Python code uses that name).

Local `pywrangler dev` can keep the placeholder. A `--local` migration creates a SQLite file on this machine and does not touch the Cloudflare account. The real id is required only for the remote database.

Create the table on the remote database:

```bash
npx wrangler d1 migrations apply bale-bot-users --remote
```

Wrangler runs the SQL files in `migrations/` in order and records which files already ran, so applying twice is safe. Then publish the Worker so the running version receives the binding:

```bash
uv run pywrangler deploy
```

Deploying before the migration still answers users. Upserts log an error until the table exists. Webhook and the minute cron both go through `handle_update`, so both paths register the user. A retried update is counted once.

Local dev uses a separate SQLite file:

```bash
npx wrangler d1 migrations apply bale-bot-users --local
```

`migrations/0002_last_action.sql` adds `users.last_action` (`sample`, `sheba`, `faq`, or `excel`) for the return greeting. Until that migration is applied, the bot still greets by name and does not invent a previous topic. Saving a phone number does not change `last_action`.

`migrations/0003_phone.sql` adds nullable `users.phone`. Stored values look like `+989` plus 10 digits. Until that column exists, chat still works and only the phone write fails soft.

`migrations/0004_events.sql` creates `events` (`user_id`, `kind`, `detail`, `created_at` in UTC). Kinds are `excel` (text file delivered to the admin), `faq` (an answer was opened; `detail` is a short question), `sheba` (the check was started), and `sample` (the sample file was sent). `/stats` counts `users.last_seen_at` / `first_seen_at` and these rows inside the Tehran day. If the events table is missing, user counts still return and the event section says to apply the migration.

Re-run `migrations apply` after pulling this version; already-applied files are skipped.

`/users` is admin-only and lists up to 20 people, most recently seen first. `/stats` is admin-only. “Today” is midnight to next midnight in Asia/Tehran (fixed UTC+03:30, no DST): an active user has `last_seen_at` in that window, a new user has `first_seen_at` in that window, and events use `created_at` with the same bounds. Both commands are commands, not keyboard buttons. The comparison is plain text because the timestamps are fixed-width UTC ISO strings.

### 4. Secrets

Names only, also listed in `.env.example`:

- `BALE_TOKEN` — BotFather token
- `ADMIN_ID` — numeric user id, stored as a string
- `WEBHOOK_SECRET` — optional path/header check

Locally, Wrangler reads `.dev.vars` (not `.env`):

```bash
cp .env.example .dev.vars
```

`DRY_RUN=1` in that file skips the Bale network and returns the actions in the webhook JSON. Do not enable it in production.

Deployed secrets:

```bash
uv run pywrangler secret put BALE_TOKEN
uv run pywrangler secret put ADMIN_ID
uv run pywrangler secret put WEBHOOK_SECRET
```

### 5. Local dev

```bash
uv run pywrangler dev --port 43123
```

`GET /health` and `POST /webhook` are served on that port. Bale will only call an HTTPS webhook on port 443 or 88, so a public tunnel is required for live updates. Unit tests cover the bot without Cloudflare:

```bash
uv run pytest
```

Regenerate the sample workbook with `uv run python scripts/make_sample.py`.

### 6. Deploy

```bash
uv run pywrangler deploy
```

Note the `*.workers.dev` hostname from the command output.

### 7. setWebhook

Without a secret:

```bash
export BALE_TOKEN="..."
export WEBHOOK_URL="https://<worker>/webhook"
uv run python scripts/set_webhook.py
```

With `WEBHOOK_SECRET` (use a URL-safe value, no slash):

```bash
export WEBHOOK_URL="https://<worker>/webhook/<WEBHOOK_SECRET>"
uv run python scripts/set_webhook.py
```

Direct call:

```bash
curl --request POST \
  "https://tapi.bale.ai/bot${BALE_TOKEN}/setWebhook" \
  --header "Content-Type: application/json" \
  --data "{\"url\":\"${WEBHOOK_URL}\"}"
```

The Worker also exposes `POST /set-webhook` with header `X-Setup-Secret: <WEBHOOK_SECRET>` and body `{"url":"https://..."}`. The route is closed when the secret is unset. Bale’s `setWebhook` method itself only documents the `url` field, so the secret is enforced by this Worker (path segment, or `X-Webhook-Secret` on the bare path). Register the path form; Bale will not send the header for you.

An empty `url` clears the webhook, per the Bale docs.

### 8. Find your admin id

Send `/id` to the bot after the webhook is connected. Put that number in `ADMIN_ID`:

```bash
uv run pywrangler secret put ADMIN_ID
```

`/start` and `/id` also print `user_id=...` in the Worker logs (`uv run pywrangler tail`). Until `ADMIN_ID` matches, nobody sees the admin menu; uploads and the customer buttons (sample payroll file, Sheba check, FAQ) still work.

### 9. Edit texts

As the admin: `/start` → «ویرایش متن» → send a key number or name (for example `welcome`) → send the new text. «انصراف», «بازگشت», `/cancel`, and `/start` leave the flow.

Button labels are keys too (`btn_sample`, `btn_sheba`, `btn_faq`, `btn_faq_edit`, `btn_faq_back`, `btn_edit`, `btn_back`, `btn_cancel`). The next keyboard uses the saved labels. Keep those labels unique.

`excel_upload_hint` is the one sentence shown on the customer menu before an upload. If KV still holds an untouched previous default (for example the old «دریافت سمپل اکسل» or «بررسی شبا» labels), the next read replaces it with the new default. A value an admin actually saved is left as-is.

Welcome keys: `welcome` (no database, or a first visit with no name), `welcome_first` (`{name}`), `welcome_back` (`{name}`), `welcome_back_plain`, `welcome_back_topic` (`{name}` `{topic}`), `welcome_back_topic_plain` (`{topic}`). `{topic}` is the current label of the stored action. An empty `last_action` does not mention a topic.

Placeholders use `{token}`. An unknown name is left as written:

| Key | Placeholders |
| --- | --- |
| `sheba_valid`, `sheba_invalid` | `{sheba}` |
| `excel_admin_caption` | `{user_label}` `{user_id}` `{timestamp}` `{phone}` `{filename}` `{rows}` |
| `excel_admin_summary` | `{user_id}` `{timestamp}` `{first_name}` `{last_name}` `{username}` `{phone}` `{rows}` `{chars}` `{filename}` |
| `phone_saved` | `{phone}` |
| `id_reply` | `{user_id}` |
| `admin_value_prompt` | `{key}` `{current}` |
| `admin_saved` | `{key}` |
| `welcome_first`, `welcome_back` | `{name}` |
| `welcome_back_topic` | `{name}` `{topic}` |
| `welcome_back_topic_plain` | `{topic}` |
| `faq_full` | `{max}` |
| `faq_ask_question`, `faq_ask_answer` | `{current}` |
| `faq_admin_bad` | `{add}` `{delete}` |

### 9.1 Branch FAQ

FAQ entries live in the KV key `bot_faq` (not inside `bot_texts`):

```json
{
  "items": [
    {"id": "open-account", "question": "...", "answer": "..."}
  ],
  "hidden": ["hours"]
}
```

`items` is display order. `hidden` lists default ids the admin deleted, so a later deploy does not put them back. A default id that is new in code and not hidden is appended.

From the admin menu, without a redeploy:

1. «ویرایش پرسش‌ها»
2. Send the row number, then the question, then the answer
3. `جدید` adds one (10 items maximum). The word is the text key `faq_cmd_add`
4. `حذف ۲` deletes that row. The prefix is the text key `faq_cmd_delete`
5. «بازگشت», «انصراف», `/cancel`, or `/start` leaves the flow

If you rename `faq_cmd_add` or `faq_cmd_delete`, edit `faq_admin_prompt` so the hint uses the same words.

Seeded ids: `open-account`, `settlement`, `fee`, `sheba-docs`, `hours`, `payroll-file`, `trace`, `limits`. The copy is branch-placeholder text (no fixed fee or hours) and can be replaced in the admin flow.

Customers open «پرسش‌های متداول», tap a button or send a number, then use «بازگشت به پرسش‌ها» or «بازگشت». A bare number outside that screen does not open the first answer.

### 9.2 Personalized /start

Only `/start`, and only for non-admins. Leaving another flow shows the ordinary menu so «خوش برگشتی» is not repeated mid-task.

- First stored visit with `first_name`: `welcome_first`
- Later visit: «خوش برگشتی» plus the name
- If `last_action` is `sample`, `sheba`, `faq`, or `excel`, that action’s label is mentioned
- NULL or an unknown code: no topic is invented
- No `first_name`: first visit uses `welcome`; a later visit uses `welcome_back_plain`
- D1 missing or `get` failing: generic `welcome`, and the chat still works
- If only the `last_action` column is missing, the name greeting still works and no topic is invented
- If the sender is not the admin and `phone` is empty, the next message asks for a mobile number. The first button is Bale `request_contact`; typed `09…` or `+98…` is normalized lightly. «انصراف» or a menu button continues without a number. Admins are not asked, so the admin keyboard stays in place.

`welcome_hint` and `excel_upload_hint` are appended under both greetings.

Bale formats outgoing text as Markdown (`*` bold, `_` italic, with spaces around the markers). Stored text is capped around 3500 characters.

### 10. Customize Excel → text

Edit `convert_excel_to_text` in `src/excel_convert.py`. Contract: `bytes -> str`.

Default, until the column mapping is finalized:

- First worksheet only
- Non-empty rows, cells separated by tabs, rows by newlines, header included
- UTF-8
- Formula cells exported as the formula string (`data_only=False`), because an unopened file has no cached value
- Caps: 5000 rows, 50 columns, with a Persian truncation line

`src/bot.py` encodes that string as UTF-8 and uploads it to `ADMIN_ID`. Pass another callable as `BotContext.converter` if you want to experiment without editing the default.

### 11. Sample file and optional R2

`assets/sample.xlsx` is committed and uploaded as a Workers static asset (`ASSETS` binding, `run_worker_first` so `/webhook` still hits Python). The loader prefers an R2 object when the `FILES` binding exists.

To switch to R2, uncomment `r2_buckets` in `wrangler.jsonc`, then:

```bash
npx wrangler r2 bucket create bale-bot-files
npx wrangler r2 object put bale-bot-files/sample.xlsx --file assets/sample.xlsx
```

The object key must be `sample.xlsx`.

### 12. Sheba check

`src/sheba.py` → `validate_sheba`. Shape: `IR` + 24 digits. Spaces, dashes, the word «شبا», and Persian/Arabic-Indic digits are normalized. The checksum is ISO 7064 MOD 97-10 (rearranged IBAN interpreted as an integer must be `1` mod 97). Digits without the `IR` prefix are rejected.

Valid placeholder: `IR430120000000000000000001`  
Invalid: `IR000000000000000000000000`

A failed check leaves the bot waiting for another number. A valid check, «انصراف», or another menu button leaves the flow.

### User commands

| Input | Result |
| --- | --- |
| `/start` | User menu, or admin menu when the id matches. Customers without a phone are then asked for one |
| `/id` | Replies with the numeric user id |
| `/users` | Admin only: recent users from D1 |
| `/stats` | Admin only: today’s counts in Tehran time |
| `/cancel` | Cancels Sheba entry, text editing, or the phone prompt |
| Payroll sample button | `sendDocument` of `sample.xlsx` to that chat |
| Sheba button | Asks for an IBAN |
| FAQ button | Lists branch questions; a number or button shows the answer |
| `.xlsx` document | Download via `getFile`, convert, `sendDocument` to `ADMIN_ID`, then acknowledge the sender |

Bale’s `getFile` limit in the docs is 20 MB. Larger documents are rejected before download. The text file is not sent back to the uploader.

### HTTP errors

| Status | Meaning |
| --- | --- |
| 401 `unauthorized` | Webhook or setup secret did not match |
| 500 `missing_token` | No `BALE_TOKEN` and `DRY_RUN` is off |
| 500 `missing_kv_binding` | `TEXTS` binding missing |
| 400 `bad_json` | Body was not a JSON object |

Client implementation: `src/bale.py`.
