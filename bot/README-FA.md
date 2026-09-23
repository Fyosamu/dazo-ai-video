# راهنمای فارسی ربات تلگرام MoneyPrinterTurbo 🎬

با یک پیام در تلگرام، کل پروسه ساخت ویدیو انجام می‌شود:
**موضوع ⇢ متن انگلیسی با LLM ⇢ دانلود استوک ⇢ گوینده و زیرنویس انگلیسی ⇢ مونتاژ ⇢ ارسال ویدیو**

- رابط ربات: **فارسی** 🇮🇷
- محتوای ویدیو: **انگلیسی** 🇬🇧 (گوینده Edge TTS + زیرنویس انگلیسی، عمودی ۹:۱۶)

---

## ۱) اجزا

| مسیر | نقش |
|---|---|
| `MoneyPrinterTurbo/` | خود موتور ساخت ویدیو (کد اصلی، آپدیت‌شده به آخرین نسخه) |
| `MoneyPrinterTurbo/config.toml` | کلیدهای LLM و Pexels اینجا تنظیم می‌شود |
| `api.bat` | سرویس API (پورت 8080) — ربات به آن وصل می‌شود |
| `start.bat` | رابط وب WebUI (پورت 8501) — برای تنظیمات گرافیکی |
| `update.bat` | آپدیت کد + وابستگی‌ها |
| `bot/bot.py` | ربات تلگرام (چسب یک‌پیامی) |
| `bot/bot.env` | تنظیمات ربات (از روی `bot.env.example`) |
| `bot/docker-compose.bot.yml` | استقرار ربات روی سرور لینوکس با Docker |

---

## ۲) اجرا روی ویندوز

1. دوبل‌کلیک روی **`api.bat`** — سرویس ساخت ویدیو بالا می‌آید (پورت 8080).
2. تست سلامت بدون هیچ کلیدی:

   ```
   python bot\bot.py --test
   ```

   اگر پایانش `✅ کل پایپ‌لاین سالم است` بود، یعنی TTS، زیرنویس، ffmpeg و API همه سالم‌اند.
   ویدیوی نمونه در `bot\out\` ذخیره می‌شود.

3. اجرای ربات (نیاز به توکن — بخش ۳):

   ```
   python bot\bot.py
   ```

---

## ۳) ساخت توکن تلگرام (۱ دقیقه)

1. در تلگرام به **@BotFather** بروید.
2. `/newbot` ← یک نام و یک یوزرنیم بدهید.
3. توکن را کپی کنید (شکلش مثل `123456789:AAH...` است).
4. در `bot/bot.env` بگذارید:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH...
   ```
5. ربات را اجرا کنید و در تلگرام `/start` بزنید.

> 🔒 برای اینکه فقط خودتان استفاده کنید، شناسه عددی‌تان را هم بگذارید:
> `ALLOWED_CHAT_IDS=123456789` (شناسه را از طریق رباتی مثل `@userinfobot` بگیرید)

---

## ۴) کلیدها (برای ساخت واقعی ویدیو)

فایل **`MoneyPrinterTurbo/MoneyPrinterTurbo/config.toml`** را با Notepad باز کنید:

### الف) کلید مدل زبانی (برای نوشتن متن ویدیو)

یکی از گزینه‌ها را انتخاب و کلیدش را بگذارید (مثال‌ها):

```toml
# DeepSeek (ارزان و سریع)
llm_provider = "deepseek"
deepseek_api_key = "sk-xxxxxxxx"

# یا Moonshot/Kimi
# llm_provider = "moonshot"
# moonshot_api_key = "sk-xxxxxxxx"

# یا OpenAI
# llm_provider = "openai"
# openai_api_key = "sk-xxxxxxxx"
```

### ب) کلید Pexels (برای ویدیوهای استوک رایگان)

1. در <https://www.pexels.com/api/> ثبت‌نام کنید و کلید رایگان بگیرید.
2. در همان `config.toml`:

```toml
pexels_api_keys = ["xxxxxxxxxxxxxxxx"]
```

3. سرویس `api.bat` را **ری‌استارت** کنید.

> بدون این دو کلید، ساخت ویدیوی اتوماتیک خطا می‌دهد (ربات همان خطا را به فارسی توضیح می‌دهد).

---

## ۵) استقرار روی سرور لینوکس (مصرف نکردن اینترنت شخصی)

با این روش **همهٔ ترافیک ساخت ویدیو** (دانلود استوک، LLM، رندر) روی سرور انجام می‌شود؛
از سیستم شما فقط پیام تلگرام مصرف می‌شود. ربات نیازی به پورت ورندی ندارد (اتصال بیرونی به تلگرام).

### پیش‌نیاز: یک سرور لینوکس (مثلاً Ubuntu 22.04) + Docker

```bash
# ۱. پوشه پروژه را روی سرور ببرید (یا git clone)
scp -r D:\MoneyPrinterTurbo\bot user@SERVER:~/mpt-bot
scp D:\MoneyPrinterTurbo\MoneyPrinterTurbo\config.toml user@SERVER:~/mpt-bot/

# ۲. فایل compose اصلی پروژه را هم بگیرید
scp D:\MoneyPrinterTurbo\MoneyPrinterTurbo\docker-compose.release.yml user@SERVER:~/mpt-bot/

# ۳. روی سرور
cd ~/mpt-bot
printf 'TELEGRAM_BOT_TOKEN=توکن_شما\n' > .env

docker compose -f docker-compose.release.yml -f docker-compose.bot.yml up -d --build

# مشاهده وضعیت
docker compose -f docker-compose.release.yml -f docker-compose.bot.yml ps
docker logs -f moneyprinterturbo-bot
```

تصویر رسمی `ghcr.io/harry0703/moneyprinterturbo:latest` از قبل ساخته شده است؛
`config.toml` (با کلیدها) و `storage/` هم به کانتینرها mount می‌شوند.

- WebUI از بیرون باز نمی‌شود (فقط `127.0.0.1:8501` روی سرور). برای دسترسی راه دور:
  `ssh -L 8501:127.0.0.1:8501 user@SERVER` سپس مرورگر: `http://127.0.0.1:8501`
- اگر سرور داخل ایران است و تلگرام فیلتر است: در `.env` پروکسی بدهید:
  `HTTPS_PROXY=http://پروکسی:پورت`

---

## ۶) دستورهای ربات (در تلگرام)

| دستور | کار |
|---|---|
| هر متن دلخواه | ساخت ویدیوی انگلیسی از همان موضوع + ارسال فایل |
| `/status` | وضعیت ۵ ویدیوی اخیر |
| `/ping` | بررسی اتصال به سرور ساخت |
| `/start` `/help` | راهنما |

---

## ۷) عیب‌یابی

| پیام فارسی ربات | دلیل | راه‌حل |
|---|---|---|
| 🔑 کلید Pexels تنظیم نشده | `pexels_api_keys` خالی است | بخش ۴ب |
| 🔑 یک کلید API تنظیم نشده | کلید LLM ندارید | بخش ۴الف |
| ❌ سرور ساخت ویدیو در دسترس نیست | `api.bat` خاموش است | `api.bat` را اجرا کنید |
| 🌐 خطای اتصال | اینترنت/پروکسی | `HTTPS_PROXY` در `bot.env` |
| 🚦 صف ساخت پر است | هم‌زمانی زیاد | چند لحظه بعد |

لاگ سرور: `D:\MoneyPrinterTurbo\api_server.log`
خروجی ویدیوها: `MoneyPrinterTurbo\storage\tasks\<شناسه>\final-1.mp4`

---

## ۸) تست بدون تلگرام و بدون کلید

```bash
python bot\bot.py --ping    # سلامت سرویس
python bot\bot.py --test    # کل پایپ‌لاین با متریال محلی (بدون LLM/Pexels)
```
