#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نمونه کامل ربات (نسخه2 — جایگزین نمونه قبلی)
  - ویدیوی13 دقیقه‌ای انگلیسی با زیرنویس بک‌گراند گرد70٪ تیرگی
  - گوینده زن طبیعی: en-US-AvaMultilingualNeural (سرعت نرمال1.0)
  - تامنیل با هوش مصنوعی گوگل (Gemini Image) + متن هوک
  - عنوان/هوک/کپشن/توضیحات/هشتگ متفاوت هر بار (Gemini)
  - جایگزینی کامل فایل‌های قبلی در Dazo + پوشه پروژه

اجرا:
  python make_sample.py --quick   # تست سریع (~6 دقیقه)
  python make_sample.py           # نمونه کامل13 دقیقه‌ای (حدود2-3 ساعت CPU)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bot as botlib

CFG = botlib.CFG
MPT = botlib._base()
HEADERS = botlib._headers()
HERE = Path(__file__).resolve().parent
DAZO = Path(os.environ.get("MPT_OUT_DIR") or (Path.home() / "Desktop" / "Dazo"))
THEIR = Path(os.environ.get("MPT_PROJECT_DIR") or Path(__file__).resolve().parents[1])
QUICK = "--quick" in sys.argv
DAILY = "--daily" in sys.argv

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-flash-lite-latest:generateContent"
)
VOICE = "en-US-EmmaMultilingualNeural-Female"  # Emma: گرم‌تر و نرم‌تر از Ava
TOPIC = os.environ.get("MPT_TOPIC") or (
    "Why humans really get angry — the three-billion-year-old switch inside us: "
    "single cells that first learned war, the amygdala hijack, modern life "
    "burning ancient fuel, and how watching your own anger rewires it"
)
THUMB_TEXT = "YOUR ANGER IS 3 BILLION YEARS OLD"

# اسکریپت کوتاه برای تست سریع (فقط --quick)
QUICK_SCRIPT = """You think you lost your temper this morning? You didn't. Something much older than you pressed a button that has been waiting three billion years to be pushed.
Every human today is built from a chain of single cells that learned to fight long before brains existed. Anger is not a glitch in your personality. It is software, written by evolution, still running on hardware you mistake for you.
Watch what happens inside your body. A threat appears, real or imagined. In less than two tenths of a second, the amygdala hijacks your thinking brain. Adrenaline floods your blood. Your fists clench. Your voice changes. The fight response activates before you are even consciously aware of the danger.
This is the upgraded cell talking. Energy meant for escaping a predator now has nowhere to go in an office, in a traffic jam, in a text message. The rage you feel is ancient fuel burned in a modern cage.
But here is the part nobody tells you: the chemical storm of anger lasts about ninety seconds. Everything after that is you re-triggering yourself with thoughts. The person who knows this owns a superpower, because you cannot be hijacked by a switch you can observe.
The next time your chest tightens, do not fight the fire and do not feed it. Just watch it. Count to ninety. And remember: the cell that learned to rage three billion years ago does not have to make your decisions for you."""
QUICK_TERMS = ["angry man", "human brain", "anger", "volcano eruption", "storm clouds"]


def gemini(prompt: str, max_tokens: int = 4096, tries: int = 3) -> str:
    key = CFG.get("GEMINI_KEY") or ""
    if not key:
        raise RuntimeError("GEMINI_KEY خالی است")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    last = None
    for i in range(tries):
        try:
            r = requests.post(
                GEMINI_URL,
                headers={"x-goog-api-key": key},
                json=body,
                timeout=150,
            )
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except Exception as exc:  #503 تقاضای بالا — کمی صبر و تکرار
            last = exc
            time.sleep(5 + i * 5)
    raise RuntimeError(f"gemini failed: {last}")


def gemini_json(prompt: str, max_tokens: int = 2048) -> dict:
    txt = gemini(prompt, max_tokens=max_tokens)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError(f"no json in reply: {txt[:120]}")
    return json.loads(m.group(0))


def build_script() -> str:
    prompt = f"""Write the full narration script for a YouTube science video.
TOPIC: {TOPIC}
REQUIREMENTS:
- Length: between1600 and2900 words (11 to20 minutes spoken at ~145 words/minute).
  Judge by the topic itself: if it is shallow, stay around1600-1900; if deep and rich,
  go all the way to2900. Never below1600, never above2900.
- Everything in English, spoken style, natural and captivating, for adults.
- Open with a strong curiosity hook that repeats the topic/title in the first sentence.
- Then break it into clear sections flowing naturally (no section labels, no markdown, no timestamps).
- NATURAL PAUSES: insert a blank line between sections, and occasionally before a revelation
  or after a surprising fact (about one blank line every3-5 sentences, NEVER on every sentence).
  Blank lines become natural ~1 second breathing pauses in the voice.
- Science + personality/psychology angle, concrete examples, small surprises, "why" and "how" answered to the root.
- End with a thought-provoking closing line and a soft subscribe ask.
- Output ONLY the narration text, plain, no headings, no asterisks."""
    script = gemini(prompt, max_tokens=8192)
    words = len(script.split())
    print(f"[script] {words} words (~{words/145:.1f} min)", flush=True)
    return script


def build_terms() -> list:
    script_head = (HERE / "_last_script.txt").read_text(encoding="utf-8")[:2500]
    txt = gemini(
        "From this narration script, list10 short Pexels video-search phrases "
        "(2-4 English words each, concrete visible footage). JSON array only.\n\n"
        + script_head,
        max_tokens=1024,
    )
    m = re.search(r"\[.*\]", txt, re.S)
    terms = [str(t) for t in json.loads(m.group(0))[:10]] if m else list(QUICK_TERMS)
    print(f"[terms] {terms}", flush=True)
    return terms


def build_metadata(script: str) -> dict:
    prompt = f"""For a YouTube video, return STRICT JSON with keys:
"title" (<=70 chars, curiosity hook, no quotes inside),
"hook" (<=6 words, punchy, UPPERCASE-able, for thumbnail overlay),
"caption" (3-4 sentences, curiosity-provoking, makes someone say "oh really?", English),
"description" (YouTube description: strong first line, then "IN THIS VIDEO:" with5-7 section bullets derived from the script, then a closing line),
"hashtags" (array of7 strings WITHOUT the # sign, relevant to psychology/science of anger).
TOPIC: {TOPIC}
SCRIPT:\n{script[:6000]}"""
    meta = gemini_json(prompt, max_tokens=3072)
    for k in ("title", "hook", "caption", "description"):
        meta[k] = str(meta.get(k) or "").strip()
    meta["hashtags"] = [str(h).lstrip("#") for h in (meta.get("hashtags") or [])][:8]
    print(f"[meta] {meta['title']}", flush=True)
    return meta


def wait_task(task_id: str, timeout=21600):
    deadline = time.time() + timeout
    last = -1
    while time.time() < deadline:
        task = botlib.get_task(task_id)
        state = int(task.get("state", 4))
        pct = int(task.get("progress") or 0)
        if pct != last:
            print(f"[task] state={state} progress={pct}%", flush=True)
            last = pct
        if state == 1:
            return task
        if state == -1:
            raise RuntimeError(f"task failed: {task.get('error')}")
        time.sleep(15)
    raise RuntimeError("task timeout")


def submit_and_wait(payload: dict, label: str, timeout: int = 21600):
    """ثبت تسک + پایش با تکرار خودکار روی خطاهای گذرای TTS."""
    for attempt in range(3):
        r = requests.post(f"{MPT}/api/v1/videos", json=payload, headers=HEADERS, timeout=60)
        task_id = botlib._checked(r)["data"]["task_id"]
        print(f"[submit {label}] {task_id} (attempt {attempt + 1}/3)", flush=True)
        try:
            return task_id, wait_task(task_id, timeout=timeout)
        except RuntimeError as exc:
            if attempt < 2 and "synthesize" in str(exc):
                print(f"[!] TTS transient — retry in30s: {exc}", flush=True)
                time.sleep(30)
            else:
                raise
    raise RuntimeError("submit failed")


def ensure_server():
    """روزانه: اگر سرور خاموش است (مثلاً بعد از ری‌استارت ویندوز) خودش بالا بیاید."""
    if botlib.mpt_ping():
        return
    print("[server] API down — starting …", flush=True)
    mpt_dir = THEIR / "MoneyPrinterTurbo"
    env = {**os.environ, "PYTHONUTF8": "1"}
    if os.name == "nt":
        env["FFMPEG_BINARY"] = str(
            THEIR / "lib/ffmpeg/ffmpeg-7.0-essentials_build/ffmpeg.exe"
        )
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        kwargs = {"creationflags": flags}
    else:
        env["FFMPEG_BINARY"] = os.environ.get("FFMPEG_BINARY", "ffmpeg")
        kwargs = {"start_new_session": True}
    log = open(THEIR / "api_server.log", "ab")
    subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(mpt_dir),
        env=env,
        stdout=log,
        stderr=log,
        **kwargs,
    )
    for _ in range(40):
        time.sleep(3)
        if botlib.mpt_ping():
            return
    raise RuntimeError("API server did not start")


def wait_idle():
    """تا آزاد شدن موتور رندر صبر کن (اجازه اجرای هم‌زمان دو تسک نده)."""
    for _ in range(72):  # حداکثر ~6 ساعت
        try:
            r = requests.get(
                f"{MPT}/api/v1/tasks?page=1&page_size=5",
                headers=HEADERS,
                timeout=20,
            )
            busy = any(int(t.get("state", 1)) == 4 for t in r.json()["data"]["tasks"])
        except Exception:
            busy = False
        if not busy:
            return
        print("[daily] render in progress — waiting5 min …", flush=True)
        time.sleep(300)


def pop_topic() -> str:
    """یک موضوع تازه و استفاده‌نشده از بانک10هزارتایی (بدون تکرار تا انتها)."""
    import csv as _csv
    import random

    qfile = THEIR / "topics_10000.csv"
    used_file = THEIR / "publish" / "used_topics.txt"
    used_file.parent.mkdir(parents=True, exist_ok=True)
    used = (
        set(used_file.read_text(encoding="utf-8").split())
        if used_file.exists()
        else set()
    )
    fresh = []
    with open(qfile, encoding="utf-8-sig") as fh:
        for row in _csv.DictReader(fh):
            if row.get("id") not in used:
                fresh.append(row)
    if not fresh:
        raise RuntimeError("topics exhausted")
    row = random.choice(fresh)
    with open(used_file, "a", encoding="utf-8") as fh:
        fh.write(row["id"] + "\n")
    print(f"[daily] topic #{row['id']}: {row['title']}", flush=True)
    return row["title"]


def main():
    global TOPIC, DAZO
    if DAILY:
        ensure_server()
        wait_idle()
        TOPIC = pop_topic()
        if not os.environ.get("MPT_OUT_DIR"):
            DAZO = THEIR / "publish" / time.strftime("%Y-%m-%d_%H%M")
        os.environ["MPT_COPY_PROJECT"] = "0"
    DAZO.mkdir(parents=True, exist_ok=True)
    if not botlib.mpt_ping():
        print("MPT API down")
        sys.exit(1)

    #1متن‌ها (LLM) ---------------------------------------------------------------
    print("[1] script …", flush=True)
    script = QUICK_SCRIPT if QUICK else build_script()
    (HERE / "_last_script.txt").write_text(script, encoding="utf-8")
    terms = QUICK_TERMS if QUICK else build_terms()
    print("[1] metadata …", flush=True)
    meta = build_metadata(script)

    #2تامنیل با هوش مصنوعی گوگل ------------------------------
    print("[2] thumbnail (Gemini Image) …", flush=True)
    thumb_text = meta.get("hook") or THUMB_TEXT
    botlib.make_thumbnail(TOPIC, thumb_text, DAZO / "thumbnail.jpg")
    print(f"[2] thumbnail ok — text: {thumb_text}", flush=True)

    #3 تسک ویدیو ---------------------------------------------
    print(f"[3] submit ({'quick' if QUICK else 'FULL ~13min'}) …", flush=True)
    payload = {
        "video_subject": TOPIC,
        "video_script": script,
        "video_terms": terms,
        "video_language": "English",
        "video_source": "pexels",
        "video_aspect": "9:16",
        "voice_name": VOICE,
        "voice_rate": 0.95,   # کمی آرام‌تر → لحن نرم‌تر و طبیعی‌تر (ضد ربات‌گونه)
        "voice_volume": 1.0,
        "subtitle_enabled": True,
        "subtitle_position": "bottom",
        "text_background_color": "#000000",   # بک‌گراند تیره70٪ (alpha پچ شد)
        "rounded_subtitle_background": True,   # گرد، تیز نیست
        "bgm_type": "random",
        "bgm_volume": 0.2,
        "video_count": 1,
        "video_clip_duration": 8,
        "n_threads": 8,
    }
    print("[4] rendering …", flush=True)
    task_id, task = submit_and_wait(payload, "FULL11-20min")
    video = botlib.download_video(task_id, task, DAZO)
    final = DAZO / "sample_video.mp4"
    if final.exists():
        final.unlink()
    shutil.move(str(video), str(final))

    #4b شورت خلاصه ~60 ثانیه‌ای از همان ویدیو (بدون مقدمه سینمایی — هوک فوری)
    print("[5] SHORT ~60s …", flush=True)
    short_script = gemini(
        "Condense this narration into a punchy vertical YouTube SHORT script, "
        "exactly135-150 words (~60 seconds spoken): a strong hook in the very "
        "first sentence, the two best insights, and a curiosity cliffhanger "
        "ending. English, spoken style. Output ONLY the narration, no headings.\n\n"
        + script[:5000],
        max_tokens=1024,
    )
    spayload = dict(payload)
    spayload["video_script"] = short_script
    spayload["video_terms"] = terms[:5]
    stask_id, stask = submit_and_wait(spayload, "SHORT")
    svid = botlib.download_video(stask_id, stask, DAZO, intro=False)
    sfinal = DAZO / "short_video.mp4"
    if sfinal.exists():
        sfinal.unlink()
    shutil.move(str(svid), str(sfinal))
    print("[5] short ok", flush=True)

    #5 نوشتن همه فایل‌ها --------------------------------------
    tags_line = " ".join(f"#{h}" for h in meta["hashtags"])
    (DAZO / "title.txt").write_text(meta["title"], encoding="utf-8")
    (DAZO / "hook.txt").write_text(thumb_text, encoding="utf-8")
    (DAZO / "caption.txt").write_text(
        meta["caption"] + ("\n\n" + tags_line if tags_line else ""), encoding="utf-8"
    )
    (DAZO / "description.txt").write_text(
        meta["description"] + ("\n\n" + tags_line if tags_line else ""), encoding="utf-8"
    )
    (DAZO / "script.txt").write_text(script, encoding="utf-8")

    #6 جایگزینی در پوشه پروژه (فقط حالت نمونه) ---------------------
    if os.environ.get("MPT_COPY_PROJECT", "1") != "0":
        names = [
            "sample_video.mp4", "short_video.mp4", "thumbnail.jpg", "title.txt", "hook.txt",
            "caption.txt", "description.txt", "script.txt",
        ]
        for n in names:
            src = DAZO / n
            if src.exists():
                shutil.copy2(src, THEIR / n)

    #7 بررسی ---------------------------------------------------
    out = subprocess.run(
        [CFG["FFMPEG"], "-hide_banner", "-ss", "00:00:06", "-i", str(final),
         "-frames:v", "1", "-y", str(DAZO / "frame_check.png")],
        capture_output=True, text=True, errors="replace",
    )
    info = subprocess.run(
        [CFG["FFMPEG"], "-hide_banner", "-i", str(final)],
        capture_output=True, text=True, errors="replace",
    )
    for line in (info.stderr or "").splitlines():
        if "Duration" in line or "Stream #" in line:
            print(line, flush=True)
    print(f"\nDazo: {DAZO}", flush=True)
    print(f"Project: {THEIR}", flush=True)


if __name__ == "__main__":
    main()
