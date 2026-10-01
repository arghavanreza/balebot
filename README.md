# بازوی بله — تبدیل اکسل / Bale Excel bot
Persian Bale bot on a **Python Cloudflare Worker**. A customer sends an `.xlsx` file; the Worker turns the first sheet into a UTF-8 text file and sends that file to the admin (not back to the customer). The same bot can hand out a sample workbook and check an Iranian Sheba (IBAN). Every customer-facing string is stored in Workers KV and can be edited from the admin menu.

مستندات API بله: <https://docs.bale.ai/>

---

## فارسی

### این بازو چه می‌کند

- دریافت فایل `.xlsx`، تبدیل شیت اول به متن جداشده با تب، و ارسال همان فایل متنی برای `ADMIN_ID`.
- دکمهٔ «دریافت سمپل اکسل»: ارسال `assets/sample.xlsx` برای خود کاربر.
- دکمهٔ «بررسی شبا»: دریافت شماره شبا و پاسخ معتبر / نامعتبر (IR به‌علاوهٔ ۲۴ رقم، الگوریتم ISO 7064 mod-97).
- اگر شناسهٔ فرستنده با `ADMIN_ID` یکی باشد، منوی مدیر نشان داده می‌شود و متن‌ها از همان‌جا قابل ویرایش‌اند.
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

بعد از این، `/start` برای آن شناسه منوی مدیر را نشان می‌دهد و برای بقیه خوش‌آمد و دو دکمهٔ کاربر را.

### ۹. ویرایش متن‌ها (مدیر)

1. `/start`
2. «ویرایش متن»
3. شماره یا نام کلید را بفرستید (مثلاً `1` یا `welcome`)
4. متن جدید را در پیام بعدی بفرستید
5. «انصراف»، «بازگشت»، `/cancel` یا `/start` جریان را قطع می‌کند

کلیدها و متن پیش‌فرض در `src/texts.py` هستند. برچسب دکمه‌ها هم کلیدند (`btn_sample`، `btn_sheba`، `btn_edit`، `btn_back`، `btn_cancel`). بعد از ذخیره، کیبورد بعدی برچسب جدید را نشان می‌دهد. برچسب‌ها را تکراری نگذارید.

جای‌نگهدارها فقط به شکل `{name}` جایگزین می‌شوند:

| کلید | جای‌نگهدار |
| --- | --- |
| `sheba_valid` / `sheba_invalid` | `{sheba}` |
| `excel_admin_caption` | `{user_label}` `{user_id}` `{filename}` `{rows}` |
| `id_reply` | `{user_id}` |
| `admin_value_prompt` | `{key}` `{current}` |
| `admin_saved` | `{key}` |

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
| `/start` | منوی کاربر یا مدیر |
| `/id` | نمایش شناسهٔ عددی |
| `/cancel` | لغو جریان فعلی |
| دریافت سمپل اکسل | ارسال نمونه |
| بررسی شبا | درخواست شبا؛ تا پاسخ معتبر یا انصراف در همین حالت می‌ماند |
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
- Reply-keyboard button «دریافت سمپل اکسل» sends `assets/sample.xlsx` so customers can see the expected columns (`name`, `amount`, `sheba`).
- Reply-keyboard button «بررسی شبا» asks for an Iranian IBAN and answers valid or invalid.
- When the sender’s numeric id equals `ADMIN_ID`, `/start` shows an admin menu that edits every customer-facing string at runtime (Workers KV, not a redeploy).
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

`/start` and `/id` also print `user_id=...` in the Worker logs (`uv run pywrangler tail`). Until `ADMIN_ID` matches, nobody sees the admin menu; uploads and the two user buttons still work.

### 9. Edit texts

As the admin: `/start` → «ویرایش متن» → send a key number or name (for example `welcome`) → send the new text. «انصراف», «بازگشت», `/cancel`, and `/start` leave the flow.

Button labels are keys too (`btn_sample`, `btn_sheba`, `btn_edit`, `btn_back`, `btn_cancel`). The next keyboard uses the saved labels. Keep those labels unique.

`{name}` placeholders (anything else is left untouched):

| Key | Placeholders |
| --- | --- |
| `sheba_valid`, `sheba_invalid` | `{sheba}` |
| `excel_admin_caption` | `{user_label}` `{user_id}` `{filename}` `{rows}` |
| `id_reply` | `{user_id}` |
| `admin_value_prompt` | `{key}` `{current}` |
| `admin_saved` | `{key}` |

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
| `/start` | User menu, or admin menu when the id matches |
| `/id` | Replies with the numeric user id |
| `/cancel` | Cancels Sheba entry or text editing |
| Sample button | `sendDocument` of `sample.xlsx` to that chat |
| Sheba button | Asks for an IBAN |
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
