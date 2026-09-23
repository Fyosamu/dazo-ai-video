#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MoneyPrinterTurbo Telegram glue bot (ربات وصل‌کننده تلگرام)

یک پیام ⇢ کل پروسه ساخت ویدیو:
    کاربر موضوع را می‌فرستد
      ⇢ ربات فارسی پاسخ می‌دهد
      ⇢ MoneyPrinterTurbo API ویدیوی انگلیسی (گوینده + زیرنویس انگلیسی) را می‌سازد
      ⇢ ربات ویدیو را در همان چت برمی‌گرداند

رابط ربات: فارسی | محتوای ویدیو: انگلیسی

Dependencies: فقط requests (همراه با خود MoneyPrinterTurbo نصب است).

Modes:
    python bot.py            اجرای ربات تلگرام (نیاز به TELEGRAM_BOT_TOKEN)
    python bot.py --test     تست کامل پایپ‌لاین بدون تلگرام و بدون کلید API
    python bot.py --ping     بررسی اتصال به سرور MoneyPrinterTurbo

Config: متغیرهای محیطی، یا فایل bot.env کنار همین اسکریپت (متغیر محیطی برنده است).
"""

import argparse
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import textwrap
import time
from pathlib import Path

import requests

# خروجی UTF-8 در ویندوز (کنسول‌های cp1252/cp1256 در غیر این صورت روی متن فارسی crash می‌کنند)
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = Path(__file__).resolve().parent
DEFAULT_MPT_ROOT = HERE.parent / "MoneyPrinterTurbo"
BUNDLED_FFMPEG = (
    HERE.parent
    / "lib"
    / "ffmpeg"
    / "ffmpeg-7.0-essentials_build"
    / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
)

DEFAULTS = {
    # تلگرام
    "TELEGRAM_BOT_TOKEN": "",
    "ALLOWED_CHAT_IDS": "",  # خالی = همه مجاز؛ مثال: "123,456"
    "HTTPS_PROXY": "",  # مثلا http://127.0.0.1:10809 اگر تلگرام فیلتر است
    # سرویس MoneyPrinterTurbo
    "MPT_API_BASE": "http://127.0.0.1:8080",
    "MPT_API_KEY": "",
    "PEXELS_KEY": "",
    "GEMINI_KEY": "",  # فقط اگر app.api_key در config.toml ست شده باشد
    # تنظیمات محتوای ویدیو (انگلیسی)
    "VIDEO_SOURCE": "pexels",  # local | pexels | pixabay | ...
    "VIDEO_ASPECT": "9:16",  # 9:16 عمودی (شورتس/تیکتاک)
    "VIDEO_VOICE": "en-US-AriaNeural-Female",
    "VIDEO_LANGUAGE": "English",
    "VIDEO_SCRIPT_PROMPT": (
        "Write the whole script in English, even if the subject is written "
        "in another language."
    ),
    "VIDEO_CLIP_DURATION": "5",
    "VIDEO_COUNT": "1",
    "BGM_VOLUME": "0.2",
    "SUBTITLE_ENABLED": "true",
    # زمان‌بندی
    "POLL_SECONDS": "10",
    "EDIT_SECONDS": "45",
    "MAX_WAIT_SECONDS": "1800",
    # فقط برای --test
    "MPT_ROOT": str(DEFAULT_MPT_ROOT),
    "FFMPEG": str(BUNDLED_FFMPEG) if BUNDLED_FFMPEG.exists() else "ffmpeg",
}

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def load_env_file(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(load_env_file(HERE / "bot.env"))
    for key in DEFAULTS:
        if key in os.environ:
            cfg[key] = os.environ[key]
    return cfg


CFG = load_config()

# پیام‌های فارسی ربات
FA_WELCOME = (
    "سلام! 👋\n"
    "من ربات ساز ویدیو هستم.\n\n"
    "🎬 کافی است یک موضوع بنویسید، مثلاً:\n"
    "«۵ عادت صبحگاهی افراد موفق»\n\n"
    "من یک ویدیوی کامل انگلیسی (گوینده + زیرنویس انگلیسی، عمودی ۹:۱۶) "
    "می‌سازم و همین‌جا تحویل می‌دهم.\n\n"
    "دستورات:\n"
    "/status — وضعیت ویدیوهای اخیر\n"
    "/ping — بررسی اتصال به سرور ساخت ویدیو\n"
    "/help — همین راهنما"
)
FA_WAIT = "⏳ یک ویدیو برای شما در حال ساخت است؛ لطفاً صبر کنید تا تمام شود."
FA_QUEUED = "📥 پیام شما در صف ساخت قرار گرفد."
FA_NO_ACCESS = "⛔ شما مجاز به استفاده از این ربات نیستید."
FA_UNSUPPORTED = "لطفاً یک متن (موضوع ویدیو) بفرستید تا ویدیو بسازم. /help برای راهنما."
FA_API_DOWN = "❌ سرور ساخت ویدیو در دسترس نیست. بعداً دوباره تلاش کنید."


def fa_digits(text) -> str:
    """تبدیل ارقام انگلیسی به فارسی برای نمایش زیباتر."""
    text = str(text)
    table = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return text.translate(table)


def fa_error(raw) -> str:
    """ترجمه خطاهای رایج MoneyPrinterTurbo به پیام فارسی روشن."""
    err = str(raw or "")
    low = err.lower()
    if "pexels_api_keys is not set" in low or "pexels" in low and "not set" in low:
        return (
            "🔑 کلید Pexels تنظیم نشده است.\n"
            "در فایل config.toml مقدار pexels_api_keys را ست کنید "
            "(کلید رایگان: https://www.pexels.com/api/)."
        )
    if "pixabay" in low and "not set" in low:
        return "🔑 کلید Pixabay تنظیم نشده است. در config.toml مقدار pixabay_api_keys را ست کنید."
    if "api_key" in low and "not set" in low or "please set it in the config" in low:
        return (
            "🔑 یک کلید API (مدل زبانی) در config.toml تنظیم نشده است.\n"
            "کلید LLM را در بخش مربوطه (مثلا deepseek_api_key یا moonshot_api_key) وارد کنید."
        )
    if "connection" in low or "timeout" in low or "timed out" in low:
        return "🌐 خطای اتصال به یک سرویس خارجی. اینترنت/پروکسی سرور را بررسی کنید."
    if "queue is full" in low or "429" in low:
        return "🚦 صف ساخت پر است؛ کمی بعد دوباره بفرستید."
    if not err:
        return "❌ ساخت ویدیو ناموفق بود (جزئیات ثبت نشد)."
    short = err if len(err) <= 300 else err[:300] + "…"
    return f"❌ ساخت ویدیو ناموفق بود:\n<code>{short}</code>"


def truncate(text: str, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def chunk(text: str, size: int = 4000) -> list:
    parts = []
    while text:
        cut = min(size, len(text))
        nl = text.rfind("\n", 0, cut)
        if nl > size // 2:
            cut = nl
        parts.append(text[:cut])
        text = text[cut:]
    return parts or [""]


# ---------------------------------------------------------------------------
# MoneyPrinterTurbo API client
# ---------------------------------------------------------------------------

SESSION = requests.Session()
if CFG["HTTPS_PROXY"]:
    SESSION.proxies = {"http": CFG["HTTPS_PROXY"], "https": CFG["HTTPS_PROXY"]}


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if CFG["MPT_API_KEY"]:
        headers["x-api-key"] = CFG["MPT_API_KEY"]
    return headers


def _base() -> str:
    return CFG["MPT_API_BASE"].rstrip("/")


def mpt_ping() -> bool:
    try:
        r = SESSION.get(f"{_base()}/ping", timeout=8)
        return r.ok and "pong" in r.text
    except requests.RequestException:
        return False


def _checked(r) -> dict:
    """پاسخ JSON را بررسی می‌کند؛ خطای سرور را به شکل خوانا بالا می‌برد."""
    if not r.ok:
        try:
            msg = r.json().get("message") or r.text[:300]
        except ValueError:
            msg = (r.text or "")[:300]
        raise RuntimeError(f"HTTP {r.status_code}: {msg}")
    data = r.json()
    if data.get("status") != 200:
        raise RuntimeError(data.get("message") or "request failed")
    return data


def create_video_task(topic: str) -> str:
    payload = {
        "video_subject": topic,
        "video_language": CFG["VIDEO_LANGUAGE"],
        "video_script_prompt": CFG["VIDEO_SCRIPT_PROMPT"],
        "video_aspect": CFG["VIDEO_ASPECT"],
        "video_source": CFG["VIDEO_SOURCE"],
        "voice_name": CFG["VIDEO_VOICE"],
        "voice_rate": 1.0,
        "subtitle_enabled": CFG["SUBTITLE_ENABLED"].lower() in ("1", "true", "yes"),
        "bgm_type": "random",
        "bgm_volume": float(CFG["BGM_VOLUME"]),
        "video_count": int(CFG["VIDEO_COUNT"]),
        "video_clip_duration": int(CFG["VIDEO_CLIP_DURATION"]),
        "paragraph_number": 1,
    }
    r = SESSION.post(
        f"{_base()}/api/v1/videos", json=payload, headers=_headers(), timeout=60
    )
    return _checked(r)["data"]["task_id"]


def get_task(task_id: str) -> dict:
    r = SESSION.get(
        f"{_base()}/api/v1/tasks/{task_id}", headers=_headers(), timeout=30
    )
    return _checked(r)["data"]


def task_outputs(task: dict) -> list:
    # «videos» = خروجی نهایی با صدا (final-*.mp4)؛
    # «combined_videos» فقط واسط بدون صداست → همیشه videos اولویت دارد.
    for key in ("videos", "combined_videos"):
        values = task.get(key)
        if values:
            return [v for v in values if isinstance(v, str) and v]
    return []


def download_candidates(uri: str) -> list:
    """آدرس‌های جایگزین برای دانلود خروجی (سازگار با endpoint خالی/ست‌شده)."""
    uri = (uri or "").strip()
    if not uri:
        return []
    if uri.startswith(("http://", "https://")):
        cands = [uri]
        idx = uri.find("/tasks/")
        if idx >= 0:
            cands.append(f"{_base()}/api/v1/download/{uri[idx + 7:]}")
        return cands
    path = uri.lstrip("/")
    cands = []
    if path.startswith("tasks/"):
        cands.append(f"{_base()}/api/v1/download/{path[6:]}")
    cands.append(f"{_base()}/api/v1/download/{path}")
    if not path.startswith("tasks/"):
        cands.append(f"{_base()}/api/v1/download/tasks/{path}")
    return cands


def polish_video(path: Path, intro: bool = True, delay_ms: int = 1100) -> Path:
    """سینمایی‌تر کردن شروع ویدیوهای اصلی (intro=True):
    -0.8 ثانیه ابتدای کاملاً سیاه
    - ظاهر شدن تدریجی (fade-in) طی ~1.4s → «کیفیت» کم‌کم زیاد می‌شود
    - صدا delay_ms می‌لی‌ثانیه دیرتر می‌آید (تصویر اول بالا می‌آید، بعد صدا)
    صدا و تصویر هم‌زمان جابه‌جا می‌شوند → زیرنویس همگام می‌ماند.
    شورت‌ها (intro=False) بدون مقدمه برمی‌گردند.
    شکست بی‌صدا = نسخه اصلی حفظ می‌شود.
    """
    import subprocess as _sp

    if not intro:
        return path
    ffmpeg = CFG.get("FFMPEG") or "ffmpeg"
    tmp = path.with_suffix(".polished.mp4")
    fc = (
        "[1:v]format=yuv420p[vb];"
        "[0:v]fade=t=in:st=0:d=1.4,format=yuv420p[vr];"
        "[vb][vr]concat=n=2:v=1:a=0[v];"
        f"[0:a]adelay={int(delay_ms)}:all=1[a]"
    )
    r = _sp.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(path),
         "-f", "lavfi", "-t", "0.8",
         "-i", "color=c=black:s=1080x1920:d=0.8:r=30",
         "-filter_complex", fc,
         "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         str(tmp)],
        capture_output=True, text=True, errors="replace",
    )
    if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return path
    tmp.replace(path)
    return path


def download_video(task_id: str, task: dict, dest_dir: Path, intro: bool = True) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    errors = []
    for uri in task_outputs(task):
        for url in download_candidates(uri):
            try:
                r = SESSION.get(
                    url, headers=_headers(), timeout=300, stream=True
                )
                if not r.ok:
                    errors.append(f"{url} -> HTTP {r.status_code}")
                    continue
                name = url.split("?")[0].rstrip("/").split("/")[-1] or "video.mp4"
                if not name.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
                    name = f"{task_id}.mp4"
                dest = dest_dir / f"{task_id}_{name}"
                with open(dest, "wb") as fh:
                    for chunk_bytes in r.iter_content(chunk_size=1024 * 256):
                        if chunk_bytes:
                            fh.write(chunk_bytes)
                if dest.stat().st_size > 0:
                    try:
                        polish_video(dest)
                    except Exception:
                        pass
                    return dest
                errors.append(f"{url} -> empty file")
            except requests.RequestException as exc:
                errors.append(f"{url} -> {exc}")
    raise RuntimeError("download failed: " + "; ".join(errors[:4]))


def tg_send_photo(chat_id: int, path: Path, caption: str = "") -> bool:
    try:
        with open(path, "rb") as fh:
            tg(
                "sendPhoto",
                timeout=120,
                files={"photo": fh},
                chat_id=chat_id,
                caption=caption[:1024] or None,
            )
        return True
    except RuntimeError:
        return False


def mpt_social(subject: str, script: str = "") -> dict:
    """عنوان + کپشن + هشتگ انگلیسی متفاوت برای هر ویدیو (از LLM سرور)."""
    payload = {
        "video_subject": subject[:500],
        "video_script": script[:8000],
        "language": "English",
        "platform": "youtube",
    }
    r = SESSION.post(
        f"{_base()}/api/v1/social-metadata",
        json=payload,
        headers=_headers(),
        timeout=180,
    )
    return _checked(r)["data"]


def make_thumbnail(topic: str, text: str, dest: Path) -> Path:
    """تامنیل: عکس مرتبط Pexels + متن کوتاه هوک (Impact) روی پس‌زمینه تیره."""
    from PIL import Image, ImageDraw, ImageFont

    key = CFG["PEXELS_KEY"]
    #1) اولویت با تصویرسازی گوگل (Gemini Image) — عکس کاملاً مرتبط با موضوع
    img = None
    raw = None
    gkey = CFG.get("GEMINI_KEY") or ""
    if gkey:
        try:
            import base64 as _b64

            gbody = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": (
                                    "Photorealistic editorial photo for a science "
                                    "video about: "
                                    f"{topic[:220]}. Clean composition, no text, "
                                    "no letters, no watermark."
                                )
                            }
                        ]
                    }
                ],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            }
            gr = SESSION.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-3.1-flash-image:generateContent",
                headers={"x-goog-api-key": gkey},
                json=gbody,
                timeout=120,
            )
            gr.raise_for_status()
            gparts = gr.json()["candidates"][0]["content"]["parts"]
            gdata = next(
                p["inlineData"]["data"]
                for p in gparts
                if p.get("inlineData") and p["inlineData"].get("data")
            )
            raw = dest.with_suffix(".raw.png")
            raw.write_bytes(_b64.b64decode(gdata))
            img = Image.open(raw).convert("RGB")
        except Exception:
            if raw is not None:
                raw.unlink(missing_ok=True)
            img = None
    if img is None and not key:
        raise RuntimeError("PEXELS_KEY خالی است")
    #2) حالت پشتیبان: عکس مرتبط Pexels
    if img is None:
        query = " ".join(re.findall(r"[A-Za-z]{4,}", topic))[:90] or "abstract"
        photos = []
        for q in (query, "science abstract"):
            r = SESSION.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": key},
                params={"query": q, "orientation": "landscape", "per_page": 5},
                timeout=30,
            )
            if r.ok:
                photos = r.json().get("photos") or []
            if photos:
                break
        if not photos:
            raise RuntimeError("pexels photo search empty")
        photo = max(photos, key=lambda p: p.get("width", 0) * p.get("height", 0))
        raw = dest.with_suffix(".raw.jpg")
        with SESSION.get(photo["src"]["large2x"], stream=True, timeout=60) as resp:
            resp.raise_for_status()
            with open(raw, "wb") as fh:
                for b in resp.iter_content(1024 * 256):
                    fh.write(b)
        img = Image.open(raw).convert("RGB")
    target, W, H = 1280 / 720, 1280, 720
    w, h = img.size
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    img = img.resize((W, H), Image.LANCZOS)
    # سایه‌ی پایین برای خوانایی متن
    shade = Image.new("L", (1, H))
    for y in range(H):
        shade.putpixel((0, y), int(max(0, (y - H * 0.4) / (H * 0.6)) * 180))
    mask = shade.resize((W, H))
    img = Image.composite(Image.new("RGB", (W, H), (8, 8, 12)), img, mask)
    draw = ImageDraw.Draw(img)
    font_small = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 24)
    lines = textwrap.wrap(text.upper(), width=22)[:3]
    # متن اصلی برجسته: بزرگ‌ترین سایزی که در عرض جا شود + خط مشکی کلفت دور حروف
    font_big = None
    stroke = 4
    for big in range(112, 47, -4):
        f = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", big)
        sw = max(4, big // 16)
        if all(
            draw.textbbox((0, 0), ln, font=f, stroke_width=sw)[2] <= W - 72
            for ln in lines
        ):
            font_big, stroke = f, sw
            break
    if font_big is None:
        font_big = ImageFont.truetype("C:/Windows/Fonts/impact.ttf", 48)
    y = H - (font_big.size + 16) * len(lines) - 46
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font_big, stroke_width=stroke)
        x = (W - (box[2] - box[0])) // 2
        draw.text(
            (x, y), line, font=font_big, fill=(255, 214, 10),
            stroke_width=stroke, stroke_fill=(0, 0, 0),
        )
        y += font_big.size + 16
    tag = "THE SCIENCE OF YOU"
    box = draw.textbbox((0, 0), tag, font=font_small)
    draw.text(((W - (box[2] - box[0])) // 2, H - 40), tag, font=font_small, fill=(255, 255, 255))
    img.save(dest, "JPEG", quality=93)
    raw.unlink(missing_ok=True)
    return dest


def run_pipeline(topic: str, status=None, cancel=None):
    """
    کل پروسه: ثبت وظیفه ⇢ پیگیری ⇢ دانلود.
    status(text) هر بار پیشرفت فارسی را دریافت می‌کند.
    خروجی: (task_id, video_path | None, error_fa | None)
    """
    task_id = create_video_task(topic)
    deadline = time.time() + int(CFG["MAX_WAIT_SECONDS"])
    poll = max(3, int(CFG["POLL_SECONDS"]))
    edit_every = max(10, int(CFG["EDIT_SECONDS"]))
    last_edit = 0.0
    last_pct = -1
    state = 4
    task = {}

    while time.time() < deadline:
        if cancel is not None and cancel.is_set():
            return task_id, None, "لغو شد."
        task = get_task(task_id)
        state = int(task.get("state", 4))
        pct = int(task.get("progress") or 0)
        if state == 1:
            if status:
                status("✅ پردازش تمام شد؛ در حال آماده‌سازی فایل نهایی…")
            path = download_video(task_id, task, HERE / "out")
            return task_id, path, None
        if state == -1:
            return task_id, None, fa_error(task.get("error"))
        now = time.time()
        if status and (now - last_edit >= edit_every or pct >= last_pct + 25):
            last_edit = now
            last_pct = (pct // 25) * 25
            status(
                "⏳ در حال ساخت ویدیو…\n"
                f"🎬 موضوع: {truncate(topic)}\n"
                f"📊 پیشرفت: ٪{fa_digits(pct)}"
            )
        if cancel is not None:
            cancel.wait(poll)
        else:
            time.sleep(poll)

    return task_id, None, (
        f"⏱ زمان ساخت تمام شد ({fa_digits(CFG['MAX_WAIT_SECONDS'])} ثانیه). "
        "وضعیت را با /status ببینید."
    )


# ---------------------------------------------------------------------------
# Telegram client
# ---------------------------------------------------------------------------


def tg_url(method: str) -> str:
    return f"https://api.telegram.org/bot{CFG['TELEGRAM_BOT_TOKEN']}/{method}"


def tg(method: str, timeout: int = 30, files: dict | None = None, **params):
    try:
        r = SESSION.post(tg_url(method), data=params, files=files, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(f"telegram unreachable: {exc}") from exc
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"telegram {method} failed")
    return data["result"]


def tg_send(chat_id: int, text: str, reply_to: int | None = None) -> int:
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to:
        params["reply_to_message_id"] = reply_to
    return tg("sendMessage", **params)["message_id"]


def tg_edit(chat_id: int, message_id: int, text: str):
    try:
        tg(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
        )
    except RuntimeError as exc:
        msg = str(exc)
        # پیام تغییر نکرده یا خیلی قدیمی شده → اهمیتی ندارد
        if "not modified" in msg or "message is not modified" in msg:
            return
        if "message to edit not found" in msg or "message is too old" in msg:
            return
        raise


def tg_send_video(chat_id: int, path: Path, caption: str) -> bool:
    try:
        with open(path, "rb") as fh:
            tg(
                "sendVideo",
                timeout=600,
                files={"video": fh},
                chat_id=chat_id,
                caption=caption[:1024],
                supports_streaming="true",
            )
        return True
    except RuntimeError as exc:
        try:
            tg_send(chat_id, f"⚠️ ارسال ویدیو ناموفق بود: <code>{exc}</code>")
        except RuntimeError:
            pass
        return False


# ---------------------------------------------------------------------------
# worker (یک وظیفه در هر زمان؛ هر چت جدا)
# ---------------------------------------------------------------------------

JOBS = queue.Queue()
ACTIVE = set()
ACTIVE_LOCK = threading.Lock()
SHUTDOWN = threading.Event()


def process_job(job: dict):
    chat_id = job["chat_id"]
    topic = job["topic"]
    try:
        msg_id = tg_send(
            chat_id,
            "✅ درخواست ثبت شد!\n"
            f"🎬 موضوع: <b>{truncate(topic, 120)}</b>\n"
            "🔧 در حال شروع ساخت ویدیوی انگلیسی (عمودی ۹:۱۶)…",
            reply_to=job.get("message_id"),
        )
    except RuntimeError:
        return

    def status(text):
        try:
            tg_edit(chat_id, msg_id, text)
        except RuntimeError:
            pass

    try:
        task_id, path, err = run_pipeline(topic, status=status, cancel=SHUTDOWN)
    except requests.RequestException:
        status(FA_API_DOWN)
        return
    except RuntimeError as exc:
        status(failed_message(str(exc), topic))
        return

    if err:
        status(failed_message(err, topic, task_id))
        return

    try:
        task = get_task(task_id)
    except requests.RequestException:
        task = {}
    script = str(task.get("script") or "").strip()

    # متادیتای متفاوت هر بار: عنوان + کپشن + هشتگ (LLM سرور)؛ در صورت نبود
    # کلید LLM از الگوی موضوع استفاده می‌شود تا ربات از کار نیفتد.
    meta_title = meta_caption = ""
    try:
        meta = mpt_social(topic, script)
        meta_title = str(meta.get("title") or "").strip()
        meta_caption = str(meta.get("caption") or "").strip()
        tags = meta.get("hashtags") or []
        if tags:
            meta_caption += "\n\n" + " ".join(
                f"#{str(t).lstrip('#')}" for t in tags[:8]
            )
    except Exception:
        meta_title = ""
        meta_caption = (
            f"{truncate(topic, 120)} — a science-based breakdown you'll wish "
            "you'd seen sooner. Full video inside."
        )
    hook_text = (meta_title or topic)[:80]

    # تامنیل جذاب با متن کوتاه
    thumb = None
    try:
        thumb = make_thumbnail(topic, hook_text, HERE / "out" / f"{task_id}_thumb.jpg")
    except Exception:
        thumb = None

    caption = f"🎬 {meta_caption}"[:1000] if meta_caption else (
        f"🎬 ویدیوی شما آماده شد!\n📌 موضوع: {truncate(topic, 90)}"
    )
    sent = tg_send_video(chat_id, path, caption)
    if thumb is not None:
        tg_send_photo(chat_id, thumb, f"🖼 تامنیل: {hook_text}")
    if sent and script:
        for part in chunk(f"📝 متن انگلیسی ویدیو:\n\n{script}"):
            try:
                tg_send(chat_id, part)
            except RuntimeError:
                break
    for f in (path, thumb):
        if f is not None:
            try:
                f.unlink()
            except OSError:
                pass


def failed_message(err: str, topic: str, task_id: str = "") -> str:
    body = err if err.startswith(("❌", "🔑", "🌐", "🚦", "⏱")) else fa_error(err)
    tid = f"\n🆔 شناسه وظیفه: <code>{task_id}</code>" if task_id else ""
    return f"{body}{tid}"


def worker_loop():
    while not SHUTDOWN.is_set():
        try:
            job = JOBS.get(timeout=1)
        except queue.Empty:
            continue
        try:
            process_job(job)
        except Exception as exc:  # هرگز نگذار ربات بیفتد
            try:
                tg_send(job["chat_id"], f"❌ خطای غیرمنتظره: <code>{exc}</code>")
            except Exception:
                pass
        finally:
            with ACTIVE_LOCK:
                ACTIVE.discard(job["chat_id"])


# ---------------------------------------------------------------------------
# دستورات و دریافت پیام‌ها
# ---------------------------------------------------------------------------

ALLOWED = {
    int(x) for x in re.findall(r"\d+", CFG["ALLOWED_CHAT_IDS"]) if x.strip()
}


def handle_command(chat_id: int, text: str):
    cmd = text.split()[0].split("@")[0].lower() if text else ""
    if cmd in ("/start", "/help"):
        tg_send(chat_id, FA_WELCOME)
    elif cmd == "/ping":
        if mpt_ping():
            tg_send(
                chat_id,
                f"✅ سرور ساخت ویدیو متصل است.\n🌐 <code>{_base()}</code>",
            )
        else:
            tg_send(chat_id, FA_API_DOWN)
    elif cmd == "/status":
        send_status(chat_id)
    else:
        tg_send(chat_id, FA_UNSUPPORTED)


def send_status(chat_id: int):
    try:
        r = SESSION.get(
            f"{_base()}/api/v1/tasks", headers=_headers(), timeout=20
        )
        r.raise_for_status()
        data = r.json().get("data") or {}
    except (requests.RequestException, ValueError):
        tg_send(chat_id, FA_API_DOWN)
        return
    if isinstance(data, list):
        tasks = data
    else:
        tasks = data.get("tasks") or []
    if not tasks:
        tg_send(chat_id, "📭 هنوز ویدیویی ساخته نشده است.")
        return
    lines = ["📋 وضعیت ویدیوهای اخیر:", ""]
    for t in tasks[:5]:
        state = int(t.get("state", 4))
        pct = fa_digits(t.get("progress") or 0)
        subject = truncate(
            ((t.get("params") or {}).get("video_subject")) or t.get("task_id", "?"), 45
        )
        if state == 1:
            icon = "✅ تکمیل"
        elif state == -1:
            icon = "❌ ناموفق"
        else:
            icon = f"⏳ در حال ساخت ٪{pct}"
        lines.append(f"• {icon} — {subject}")
    tg_send(chat_id, "\n".join(lines))


def dispatch_update(update: dict, offset_state: dict):
    offset_state["offset"] = update["update_id"] + 1
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return
    if ALLOWED and chat_id not in ALLOWED:
        try:
            tg_send(chat_id, FA_NO_ACCESS)
        except RuntimeError:
            pass
        return
    if text.startswith("/"):
        try:
            handle_command(chat_id, text)
        except RuntimeError:
            pass
        return
    topic = text[:300]
    with ACTIVE_LOCK:
        if chat_id in ACTIVE:
            try:
                tg_send(chat_id, FA_WAIT, reply_to=message.get("message_id"))
            except RuntimeError:
                pass
            return
        ACTIVE.add(chat_id)
    try:
        tg_send(chat_id, FA_QUEUED, reply_to=message.get("message_id"))
    except RuntimeError:
        pass
    JOBS.put(
        {
            "chat_id": chat_id,
            "topic": topic,
            "message_id": message.get("message_id"),
        }
    )


def run_bot():
    if not CFG["TELEGRAM_BOT_TOKEN"]:
        print(
            "❌ TELEGRAM_BOT_TOKEN تنظیم نشده است.\n"
            "   1) در تلگرام به @BotFather بروید و /newbot بزنید.\n"
            "   2) توکن را در فایل bot.env یا متغیر محیطی TELEGRAM_BOT_TOKEN بگذارید.",
            flush=True,
        )
        sys.exit(2)
    if not mpt_ping():
        print(f"⚠️  سرور MoneyPrinterTurbo در {_base()} در دسترس نیست؛ تلاش ادامه می‌یابد…", flush=True)

    worker = threading.Thread(target=worker_loop, name="mpt-worker", daemon=True)
    worker.start()

    offset = {"offset": 0}
    print(f"🤖 ربات روشن شد. سرور ویدیو: {_base()}", flush=True)
    backoff = 2
    while not SHUTDOWN.is_set():
        try:
            r = SESSION.post(
                tg_url("getUpdates"),
                data={
                    "offset": offset["offset"],
                    "timeout": 50,
                    "allowed_updates": ["message"],
                },
                timeout=70,
            )
            data = r.json()
            if not data.get("ok"):
                desc = data.get("description") or ""
                if "Unauthorized" in desc:
                    print("❌ توکن تلگرام نامعتبر است (TELEGRAM_BOT_TOKEN).", flush=True)
                    sys.exit(2)
                raise RuntimeError(desc or "getUpdates failed")
            backoff = 2
            for update in data.get("result", []):
                try:
                    dispatch_update(update, offset)
                except Exception as exc:
                    print(f"[dispatch error] {exc}", flush=True)
        except (requests.RequestException, RuntimeError) as exc:
            if SHUTDOWN.is_set():
                break
            print(f"[telegram] {exc} — retry in {backoff}s", flush=True)
            SHUTDOWN.wait(backoff)
            backoff = min(backoff * 2, 60)
    print("👋 ربات خاموش شد.", flush=True)


# ---------------------------------------------------------------------------
# تست کامل پایپ‌لاین بدون تلگرام و بدون کلید API (--test)
# ---------------------------------------------------------------------------

TEST_SCRIPT = (
    "Small daily habits shape your future more than big one-time efforts. "
    "Start every morning with a clear intention instead of your phone. "
    "Ten focused minutes of learning compound into real expertise over a year. "
    "Protect your energy by saying no to distractions that add no value. "
    "Track your progress weekly, adjust once, and keep moving forward."
)
TEST_TERMS = ["forest", "river", "mountains"]
TEST_CLIPS = {
    "mpt_test_a.mp4": "testsrc2=size=1280x720:rate=30",
    "mpt_test_b.mp4": "smptehdbars=size=1280x720:rate=30",
    "mpt_test_c.mp4": "gradients=size=1280x720:rate=30:speed=0.05",
}


def ensure_test_clips(local_dir: Path) -> list:
    """کلیپ‌های آزمایشی محلی را با ffmpeg می‌سازد (بدون اینترنت، بدون کلید)."""
    local_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = CFG["FFMPEG"]
    if not Path(ffmpeg).exists():
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError("ffmpeg پیدا نشد؛ FFMPEG را تنظیم کنید.")
        ffmpeg = found
    for name, src in TEST_CLIPS.items():
        dest = local_dir / name
        if dest.exists() and dest.stat().st_size > 100_000:
            continue
        cmd = [
            ffmpeg, "-y", "-f", "lavfi", "-i", src, "-t", "15",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast",
            str(dest),
        ]
        print(f"   ساخت کلیپ تست: {name} …", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not dest.exists():
            raise RuntimeError(f"ffmpeg failed for {name}: {proc.stderr[-400:]}")
    return sorted(TEST_CLIPS.keys())


def run_test() -> int:
    print("=" * 60)
    print("تست کامل پایپ‌لاین (بدون تلگرام، بدون کلید LLM/Pexels)")
    print("=" * 60)
    base = _base()
    print(f"1) اتصال به سرور: {base} …", end=" ", flush=True)
    if not mpt_ping():
        print("FAILED ❌")
        print("   سرور بالا نیست. ابتدا start.bat یا api.bat را اجرا کنید.")
        return 1
    print("OK ✅ (pong)")

    mpt_root = Path(CFG["MPT_ROOT"])
    local_dir = mpt_root / "storage" / "local_videos"
    print("2) تهیه کلیپ‌های محلی آزمایشی …", end=" ", flush=True)
    clips = ensure_test_clips(local_dir)
    print(f"OK ✅ ({len(clips)} کلیپ)")

    payload = {
        "video_subject": "The power of daily habits",
        "video_script": TEST_SCRIPT,
        "video_terms": TEST_TERMS,
        "video_language": "English",
        "video_source": "local",
        "video_materials": [
            {"provider": "local", "url": name, "duration": 15} for name in clips
        ],
        "video_aspect": CFG["VIDEO_ASPECT"],
        "voice_name": CFG["VIDEO_VOICE"],
        "subtitle_enabled": True,
        "bgm_type": "random",
        "bgm_volume": float(CFG["BGM_VOLUME"]),
        "video_count": 1,
        "video_clip_duration": int(CFG["VIDEO_CLIP_DURATION"]),
        "paragraph_number": 1,
    }
    print("3) ثبت وظیفه ساخت ویدیو …", end=" ", flush=True)
    try:
        r = SESSION.post(
            f"{_base()}/api/v1/videos", json=payload, headers=_headers(), timeout=60
        )
        task_id = _checked(r)["data"]["task_id"]
    except (requests.RequestException, RuntimeError) as exc:
        print("FAILED ❌")
        print(f"   {exc}")
        return 1
    print(f"OK ✅ task_id={task_id}")

    print("4) پیگیری پردازش (TTS ← زیرنویس ← مونتاژ ffmpeg) …", flush=True)
    deadline = time.time() + int(CFG["MAX_WAIT_SECONDS"])
    task = {}
    while time.time() < deadline:
        task = get_task(task_id)
        state = int(task.get("state", 4))
        pct = task.get("progress") or 0
        print(f"   state={state} progress={pct}%", flush=True)
        if state in (1, -1):
            break
        time.sleep(max(3, int(CFG["POLL_SECONDS"])))
    else:
        print("FAILED ❌ timeout")
        return 1

    if int(task.get("state", 4)) != 1:
        print("FAILED ❌")
        print(f"   {task.get('error')}")
        return 1

    print("5) دانلود ویدیوی نهایی …", end=" ", flush=True)
    try:
        path = download_video(task_id, task, HERE / "out")
    except RuntimeError as exc:
        print("FAILED ❌")
        print(f"   {exc}")
        return 1
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"OK ✅ {path} ({size_mb:.1f} MB)")

    script = str(task.get("script") or "")
    print("-" * 60)
    print("✅ کل پایپ‌لاین سالم است:")
    print("   • ساخت وظیفه API")
    print("   • گوینده Edge TTS (رایگان)")
    print("   • زیرنویس")
    print("   • مونتاژ با ffmpeg")
    print("   • دانلود خروجی")
    if script:
        print(f"   • متن ویدیو (انگلیسی): {script[:120]}…")
    print("-" * 60)
    return 0


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# بانک موضوعات — تولید N عنوان یکتا با هوک (بدون LLM، بدون توکن)
# ---------------------------------------------------------------------------

# هر ردیف: (دسته، کانون موضوع، [نگرش‌های قالبی]) — عناوین از ترکیب
# دسته × کانون × نگرش ساخته و بی‌تکرار می‌شوند.
TOPIC_CATEGORIES = {
    "Origins & Evolution": [
        "what we really are before language existed",
        "how single cells became human bodies",
        "why evolution kept fear but removed peace",
        "the first creature that learned to wait",
        "why bodies age but brains refuse to",
        "how mimicry and memory shaped societies",
        "why the human throat reshaped speech",
        "what symmetry has to do with attraction",
        "why we still carry the sea inside us",
        "how walking upright rewired emotions",
    ],
    "Emotions & The7 Sins": [
        "anger and its ancient fuel",
        "envy and the comparison machine",
        "greed and the never-full stomach",
        "sloth and the energy-saving brain",
        "pride and the fragile ego shield",
        "gluttony and the reward loop",
        "lust and the reproduction program",
        "shame and its social purpose",
        "guilt as an inner contract",
        "regret and the road not taken",
    ],
    "Why-Series (The Law of Why)": [
        "why we keep asking why before acting",
        "why no means maybe to a child's brain",
        "why rules feel heavier than reasons",
        "why habits survive when motivation dies",
        "why apologies change the body",
        "why deadlines create fake clarity",
        "why we obey strangers in uniforms",
        "why silence hurts more than insult",
        "why promises feel physical",
        "why questions rewire decision making",
    ],
    "Curiosity & Security": [
        "curiosity as an implanted safety mechanism",
        "why the unknown both scares and attracts",
        "how the brain buys safety with exploration",
        "why children test every boundary",
        "why forbidden doors pull harder",
        "why knowledge feels like armor",
        "why anxious people research instead of rest",
        "why curiosity dies in controlled environments",
        "why maps calm the ancient brain",
        "why secrets create physical tension",
    ],
    "Intelligence & Smart People": [
        "why smart people doubt themselves more",
        "what geniuses know about not knowing",
        "why the smartest pause before answering",
        "how experts think differently from crowds",
        "why curiosity beats raw intelligence",
        "what deep thinkers do with boredom",
        "why smart people change their minds fast",
        "how pattern seekers see invisible rules",
        "why learning feels like unlearning",
        "what wise people never rush",
    ],
    "Death, Life & The Balance": [
        "why we live while knowing we die",
        "how fear of the unknown fuels daily life",
        "whether this balance is really worth it",
        "why death makes mornings louder",
        "how mortality built culture and meaning",
        "why we bury death under busy schedules",
        "what the brain does with forever",
        "why legacy ideas outlive bodies",
        "how hospitals changed our fear wiring",
        "why some fears grow quieter with age",
    ],
    "Dark Psychology (20-Part Series)": [
        "part1 the foot-in-the-door technique",
        "part2 how cold reading really works",
        "part3 the broken record of manipulation",
        "part4 love bombing and its scripts",
        "part5 gaslighting and memory edits",
        "part6 the halo effect in sales",
        "part7 reverse psychology mechanics",
        "part8 scarcity pressure tactics",
        "part9 the Sunk Cost trap",
        "part10 isolation playbooks",
        "part11 flattery ladders",
        "part12 emotional blackmail patterns",
        "part13 the illusion of choice",
        "part4 anchoring in negotiations",
        "part15 triangulation tactics",
        "part16 future faking signals",
        "part17 the good-cop routine",
        "part18 obligation hooks",
        "part19 labeling and identity control",
        "part20 how to disarm every tactic",
    ],
    "Science of Relationships": [
        "why adults marry and what genes want",
        "how attachment styles pick partners",
        "why arguments follow the same script",
        "what oxytocin actually decides",
        "why attraction fades and rebuilds",
        "how childhood molds adult bonds",
        "why some couples never run out of talk",
        "what trust does to the nervous system",
        "why jealousy reappears at30",
        "how shared silence measures love",
    ],
    "Brain & Behavior": [
        "how dopamine schedules your desires",
        "why memory edits every retelling",
        "what sleep does to yesterday's problems",
        "why habits live below consciousness",
        "how stress shrinks the thinking brain",
        "why the90-second emotion rule exists",
        "what attention really costs the brain",
        "why multitasking is a lie",
        "how the gut talks to the mind",
        "why first impressions stick for years",
    ],
    "Society & Belief": [
        "how cultures form without anyone deciding",
        "why beliefs harden with age",
        "what tribes teach babies about us vs them",
        "why rituals survived every empire",
        "how language builds invisible borders",
        "why traditions outlive their reasons",
        "what money invented beyond trade",
        "why flags can move bodies",
        "how stories replace shared blood",
        "why norms feel like laws",
    ],
    "Persuasion & Influence": [
        "why mirroring bodies builds instant trust",
        "how tone of voice wins arguments",
        "why the last offer is remembered most",
        "what silence does in negotiations",
        "why people comply with tiny requests first",
        "how framing changes any answer",
        "why confidence looks like competence",
        "what names do to cooperation",
        "why asking twice reveals honesty",
        "how stories beat statistics every time",
    ],
    "Memory & Learning": [
        "why spaced repetition beats cramming",
        "how emotion decides what you remember",
        "why writing beats highlighting",
        "what boredom does for deep learning",
        "why teaching exposes fake knowledge",
        "how sleep saves the day's lessons",
        "why mnemonics hijack memory",
        "what curiosity does to retention",
        "why outlines build faster recall",
        "how mistakes glue facts to the brain",
    ],
    "Sleep & Dreams": [
        "why dreams replay yesterday's threats",
        "what the brain cleans at3am",
        "why weekends cannot repay sleep debt",
        "how one hour shifts your whole mood",
        "why nightmares keep old wounds open",
        "what screens do to melatonin",
        "why lucid dreams feel like training",
        "how naps reset willpower",
        "why boring tasks appear in dreams",
        "what chronic sleep loss steals first",
    ],
    "Fear & Anxiety": [
        "why anxiety points at the future only",
        "what the body does before panic",
        "why avoided fears grow louder",
        "how breathing rewires the alarm",
        "why uncertainty weighs more than pain",
        "what ancestors left in your startle reflex",
        "why anxiety peaks before exams and flights",
        "how labeling fear shrinks it",
        "why safe risks dissolve phobias",
        "what muscles remember from stress",
    ],
    "Motivation & Willpower": [
        "why motivation arrives after action",
        "how tiny wins automate big goals",
        "why willpower behaves like a muscle",
        "what deadlines really do to the brain",
        "why identity beats discipline",
        "how environment beats motivation",
        "why visible progress feeds itself",
        "what excuses protect you from",
        "why rest is part of effort",
        "how routines outsmart moods",
    ],
    "Money & Decisions": [
        "why the brain counts losses twice",
        "how sale tags rewrite true value",
        "why cash feels different from cards",
        "what scarcity does to IQ tests",
        "why lottery math never applies",
        "how subscriptions hide real cost",
        "why rich feel poorer than before",
        "what status spending buys emotionally",
        "why budgets fail without rules",
        "how future-you gets cheated daily",
    ],
}

# نگرش‌های قالبی امن برای فوکال‌های اسمی ({T} = عبارت اسمی)
TOPIC_ANGLES = [
    "The Hidden Science Behind {T}",
    "Scientists Just Exposed {T}",
    "What Nobody Tells You About {T}",
    "The Real Truth About {T}",
    "{T} — The Part Schools Never Teach",
    "{T} Explained in Five Minutes",
    "The #1 Myth About {T}",
    "The Dark Side of {T}",
    "The Surprising Power of {T}",
    "The Quiet Cost of {T}",
    "How {T} Changes Your Brain",
    "The Hidden Cost of {T}",
    "{T}: What Science Finally Admitted",
    "The Complete Guide to {T}",
    "Why {T} Deserves Your Attention",
    "{T} and the Safety You Never Noticed",
    "Who Really Benefits From {T}?",
    "The Ancient Roots of {T}",
    "Your Body Already Knows About {T}",
    "Smart People Study {T} First",
    "{T}: The Hidden Mechanism",
    "The Forgotten Science of {T}",
    "What Schools Skip About {T}",
    "The Untold Story of {T}",
    "{T} — And Why It Matters Today",
]

# فوکال‌های why/how/what... خودشان عنوان عالی‌اند؛ فقط پسوند هوک‌دار می‌خورند.
CLAUSE_START = re.compile(r"^(why|how|what|when|where|which)\b", re.I)
CLAUSE_LEADS = [
    "{0}",
    "{0} — Here's What Science Says",
    "{0} — The Full Story",
    "{0} (And Why It Matters)",
    "{0}: What Nobody Teaches",
    "{0} — The Part Schools Skip",
    "{0} — Science Finally Answered",
    "The Truth About {0}",
    "Understanding {0}",
    "{0} — And What It Does To You",
]

# هوک کوتاه برای روی تامنیل (هر موضوع)
HOOK_TEMPLATES = [
    "STOP: {short}",
    "THIS CHANGES {short}",
    "{short}?!",
    "THE TRUTH ABOUT {short}",
    "YOU ARE {short}",
    "SCIENCE CONFIRMS: {short}",
    "NEVER IGNORE {short}",
    "{short} — FINAL PROOF",
]

# پسوندهای کیفی‌کننده — فضای یکتایی عنوان‌ها را چند برابر می‌کنند
TOPIC_QUALIFIERS = [
    "",
    "in Adults",
    "Under Stress",
    "in Relationships",
    "at Work",
    "Before It's Too Late",
]

YT_CHECK = "https://www.youtube.com/results?search_query="


def make_title(focal: str, angle: str, variant: int) -> str:
    """فوکال clause-ای خودش عنوان است؛ فوکال اسمی با قالب امن ترکیب می‌شود."""
    if CLAUSE_START.match(focal):
        head = focal[0].upper() + focal[1:]
        title = CLAUSE_LEADS[variant % len(CLAUSE_LEADS)].format(head)
    else:
        title = angle.replace("{T}", focal[0].upper() + focal[1:])
    return title


def build_topics(count: int) -> list:
    """حلقه‌ی قطع‌شونده: کیفیت‌کننده × نگرش × دسته × کانون — بدون تکرار."""
    rows = []
    seen = set()
    for qual in TOPIC_QUALIFIERS:
        for angle in TOPIC_ANGLES:
            for cat, focals in TOPIC_CATEGORIES.items():
                for focal in focals:
                    title = make_title(focal, angle, len(seen))
                    if qual:
                        title = f"{title} ({qual})"
                    key = title.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    short = focal.split(" and ")[0].split(" with ")[0][:38].upper()
                    hook = HOOK_TEMPLATES[len(seen) % len(HOOK_TEMPLATES)].replace(
                        "{short}", short
                    )
                    terms = [w for w in re.findall(r"[a-z]{4,}", focal.lower())][:4] or [
                        "science",
                    ]
                    query = "+".join(
                        w
                        for w in re.findall(
                            r"[a-z]{4,}", (angle + " " + focal).lower()
                        )[:6]
                    )
                    rows.append(
                        {
                            "id": len(rows) + 1,
                            "category": cat,
                            "title": title,
                            "hook": hook,
                            "terms": ";".join(terms),
                            "youtube_check": YT_CHECK + query,
                        }
                    )
                    if len(rows) >= count:
                        return rows
    raise RuntimeError(
        f"unique topic space is {len(rows)} < requested {count}; add categories/focals"
    )


def cmd_topics(count: int, out: Path):
    import csv

    rows = build_topics(count)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "category", "title", "hook", "terms", "youtube_check"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} topics -> {out}")
    for row in rows[:3]:
        print(f"  #{row['id']} [{row['category']}] {row['title']}")
        print(f"      hook: {row['hook']}")


# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo Telegram glue bot")
    parser.add_argument("--test", action="store_true", help="end-to-end test without Telegram")
    parser.add_argument("--ping", action="store_true", help="check MoneyPrinterTurbo API")
    parser.add_argument("--topics", type=int, nargs="?", const=10000, default=0,
                        metavar="N", help="generate N unique topics (default10000) CSV")
    parser.add_argument("--topics-out", default=str(HERE / "topics.csv"),
                        help="output CSV path for --topics")
    args = parser.parse_args()

    if args.ping:
        ok = mpt_ping()
        print(f"{'OK' if ok else 'FAIL'}: {_base()}")
        sys.exit(0 if ok else 1)
    if args.test:
        sys.exit(run_test())
    if args.topics:
        cmd_topics(args.topics, Path(args.topics_out))
        sys.exit(0)

    def stop(signum, frame):
        SHUTDOWN.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    run_bot()


if __name__ == "__main__":
    main()
