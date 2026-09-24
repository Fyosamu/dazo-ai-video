#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
آپلود ویدیو در یوتیوب (از yt_auth.py راه‌اندازی شده):
  python yt_upload.py <video.mp4> <title> <description_file> [tags_csv] [thumbnail.jpg]
خروجی: لینک ویدیو
"""
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

HERE = Path(__file__).resolve().parent
vals = {}
for line in (HERE / "yt.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip()

creds = Credentials(
    None,
    refresh_token=vals["YT_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=vals["YT_CLIENT_ID"],
    client_secret=vals["YT_CLIENT_SECRET"],
    scopes=["https://www.googleapis.com/auth/youtube.upload"],
)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())
yt = build("youtube", "v3", credentials=creds)

video = sys.argv[1]
title = sys.argv[2][:100]
desc_file = Path(sys.argv[3]) if len(sys.argv) > 3 else None
desc = desc_file.read_text(encoding="utf-8")[:4900] if desc_file else ""
# خط افشای AI (کوتاه، آخر توضیحات — تکلیف YouTube برای محتوای ساختگی)
if desc and "AI assistance" not in desc:
    desc = desc.rstrip() + "\n\nMade with AI assistance."
tags = (
    [t.strip() for t in sys.argv[4].split(",") if t.strip()]
    if len(sys.argv) > 4 and sys.argv[4]
    else []
)[:30]
thumb = Path(sys.argv[5]) if len(sys.argv) > 5 else None

body = {
    "snippet": {
        "title": title,
        "description": desc,
        "tags": tags,
        "categoryId": "27",  # Science & Technology
    },
    "status": {
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False,
        # افشای رسمی محتوای ساختگی/ساخته‌شده با AI — تکلیف یوتیوب؛ متن جلوی بیننده نمی‌آید
        "containsSyntheticMedia": True,
    },
}
media = MediaFileUpload(video, chunksize=-1, resumable=True, mimetype="video/*")
req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
resp = None
while resp is None:
    status, resp = req.next_chunk()
    if status:
        print(f"upload {int(status.progress() * 100)}%")
print("uploaded:", "https://youtu.be/" + resp["id"])

if thumb and thumb.exists():
    yt.thumbnails().set(
        videoId=resp["id"], media_body=MediaFileUpload(str(thumb))
    ).execute()
    print("thumbnail set")
