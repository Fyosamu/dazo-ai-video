#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ثبت/به‌روزرسانی Secrets مخزن گیت‌هاب — بدون هیچ کلیدی در کد.

  GH_TOKEN=... python gh_set_secrets.py NAME VALUE [NAME VALUE ...]
"""
import base64
import json
import os
import sys
import urllib.request

import nacl.public

REPO = os.environ.get("GH_REPO", "Fyosamu/dazo-ai-video")
API = "https://api.github.com"


def req(method: str, path: str, data: dict | None = None) -> dict:
    r = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={
            "Authorization": "token " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "User-Agent": "opencode",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(r, timeout=30) as f:
        body = f.read()
        return json.loads(body) if body else {}


def main() -> None:
    args = sys.argv[1:]
    if len(args) % 2:
        raise SystemExit("usage: gh_set_secrets.py NAME VALUE ...")
    for name, value in zip(args[0::2], args[1::2]):
        pub = req("GET", f"/repos/{REPO}/actions/secrets/public-key")
        box = nacl.public.SealedBox(
            nacl.public.PublicKey(base64.b64decode(pub["key"]))
        )
        enc = base64.b64encode(box.encrypt(value.encode())).decode()
        req(
            "PUT",
            f"/repos/{REPO}/actions/secrets/{name}",
            {"encrypted_value": enc, "key_id": pub["key_id"]},
        )
        print("secret set:", name)


if __name__ == "__main__":
    main()
