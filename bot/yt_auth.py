#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اتصال یوتیوب — فقط یک بار اجرا کنید:

1) در https://console.cloud.google.com پروژه بسازید
2) OAuth consent screen → External → Save (در Draft کافی است)
3) APIs & Services → Credentials → Create Credentials → OAuth client ID
   Application type = **Desktop app** → Client ID و Client Secret را کپی کنید
4) مقادیر را در فایل bot/yt.env بگذارید (نمونه در yt.env.example)
5) اجرا:  python yt_auth.py   → مرورگر باز می‌شود → اکانت یوتیوب → Allow
6) refresh_token ذخیره می‌شود؛ دیگر لازم نیست کاری کنید.

خروجی: bot/yt.env  (هرگز کامیت نمی‌شود — در .gitignore هست)
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

HERE = Path(__file__).resolve().parent
env = HERE / "yt.env"
vals = {}
if env.exists():
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()

cid = vals.get("YT_CLIENT_ID") or input("YT_CLIENT_ID: ").strip()
sec = vals.get("YT_CLIENT_SECRET") or input("YT_CLIENT_SECRET: ").strip()

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": cid,
            "client_secret": sec,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    },
    scopes=["https://www.googleapis.com/auth/youtube.upload"],
)
creds = flow.run_local_server(port=8099, prompt="consent")

lines = [f"YT_CLIENT_ID={cid}", f"YT_CLIENT_SECRET={sec}"]
if creds.refresh_token:
    lines.append(f"YT_REFRESH_TOKEN={creds.refresh_token}")
env.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("saved:", env)
