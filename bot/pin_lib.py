# -*- coding: utf-8 -*-
"""Pinterest photo -> YouTube thumbnail, zero API key, stdlib + Pillow only.

Pipeline (safe to call from any bot, every run):

    path, src = pin_lib.thumbnail("angry woman dark portrait",
                                  "YOUR ANGER IS 3 BILLION YEARS OLD",
                                  "out/thumbnail.jpg", mode="long")

  1. search  Pinterest internal endpoint (no login, no key, no quota)
  2. download candidates + keep only the ones matching the canvas aspect
  3. compose the photo COMPLETE (never cropped through the subject) inside
     the frame, with a slim band on top that holds the headline.

Fallbacks are the caller's business: if this raises, use your old source.

Modes: "long" = 1280x720 (16:9), "short" = 720x1280 (9:16)
"""
import http.cookiejar
import json
import os
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# DNS self-heal: the local resolver sometimes answers a public hostname with a
# dead private address. netfix is optional so pin_lib stays portable.
try:
    import netfix  # noqa: F401
except Exception:                                    # noqa: BLE001
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MODES = {"long": (1280, 720), "short": (720, 1280)}
# only keep photos that already match the frame -> subject never gets cut
RULE = {"long": (1.35, 10 ** 9), "short": (0.0, 0.82)}
MIN_W = {"long": 900, "short": 560}

_FONT_CANDIDATES = (
    "C:/Windows/Fonts/impact.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/anton/Anton-Regular.ttf",
)

# ------------------------------------------------------------------ search ---


def _opener(query):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "en-US,en;q=0.9")]
    page = "https://www.pinterest.com/search/pins/?q=" + urllib.parse.quote(query)
    op.open(page, timeout=40).read()
    token = next((c.value for c in cj if c.name == "csrftoken"), None)
    return op, token, page


def search(query, page_size=30, log=print, tries=4):
    """Original-size pin image URLs for `query` (no login / no key)."""
    last = None
    for attempt in range(tries):
        try:
            return _search_once(query, page_size, log)
        except Exception as e:                       # noqa: BLE001 - retry
            last = e
            log("[pin] search retry %d/%d: %s" % (attempt + 1, tries, e))
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError("pinterest search failed for %r: %s" % (query, last))


def _search_once(query, page_size, log):
    op, token, referer = _opener(query)
    data = {"options": {"query": query, "scope": "pins", "page_size": page_size,
                        "accessibility": {"prefers_reduced_motion": False}},
            "context": {"app_version": "2026.9.26.1", "client_code": 11,
                        "browser_locale": "en-US", "csrf_token": token or ""}}
    url = ("https://www.pinterest.com/resource/BaseSearchResource/get/"
           "?source_id=%s&_=%d&data=%s"
           % (uuid.uuid4(), int(time.time() * 1000),
              urllib.parse.quote(json.dumps(data))))
    hdr = {"User-Agent": UA,
           "Accept": "application/json, text/javascript, */*; q=0.01",
           "X-Requested-With": "XMLHttpRequest",
           "X-Pinterest-AppState": "active",
           "Referer": referer,
           "Content-Type": "application/json"}
    if token:
        hdr["X-CSRFToken"] = token
    raw = op.open(urllib.request.Request(url, data=json.dumps(data).encode(),
                                         headers=hdr), timeout=45).read()
    js = json.loads(raw)
    res = (js.get("resource_response") or {}).get("data") or {}
    out = []
    for r in (res.get("results") or []):
        imgs = r.get("images") or {}
        for key in ("original", "orig", "736x", "564x"):
            u = (imgs.get(key) or {}).get("url")
            if u and u not in out:
                out.append(u)
                break
    if not out:                                   # generic fallback
        txt = raw.decode("utf-8", "ignore")
        for m in re.finditer(r"https://i\.pinimg\.com/(?:originals|736x|564x)/"
                             r"[^\"'\\s&]+?\.(?:jpg|jpeg|png|webp)", txt):
            if m.group(0) not in out:
                out.append(m.group(0))
    log("[pin] %r -> %d urls" % (query, len(out)))
    return out


def download(url, dest, timeout=60, tries=5):
    """Fetch with retries — this network resets idle/new TLS handshakes
    fairly often, so a single attempt is not enough."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    hdr = {"User-Agent": UA,
           "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
           "Referer": "https://www.pinterest.com/"}
    last = None
    for i in range(tries):
        try:
            data = urllib.request.urlopen(
                urllib.request.Request(url, headers=hdr), timeout=timeout).read()
            if len(data) < 1024:
                raise IOError("suspiciously small body (%d B)" % len(data))
            with open(dest, "wb") as f:
                f.write(data)
            return dest
        except Exception as e:                       # noqa: BLE001 - retry
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("download failed after %d tries: %s" % (tries, last))


# ------------------------------------------------------------------ choose ---


def _fits(path, mode, min_w, allow_any=False):
    """allow_any (biography): a portrait is accepted in a 16:9 frame and vice
    versa — but only inside sane bounds, so we never take a 8:1 banner."""
    try:
        with Image.open(path) as im:
            w, h = im.size
    except Exception:
        return False
    if not h:
        return False
    r = w / h
    if allow_any:
        if w < min_w or h < 400:
            return False
        return r >= 0.55 if mode == "long" else r <= 1.8
    lo, hi = RULE[mode]
    return lo <= r <= hi and w >= min_w


# hints added when the plain query only returns the "wrong" orientation
_HINTS = {
    "long": (" wide", " landscape", " horizontal banner", " 16:9"),
    "short": (" vertical", " portrait", " 9:16"),
}


def _queries(query, mode):
    """Retry with orientation hints until we get photos that fit natively."""
    out = [query]
    for h in _HINTS[mode]:
        out.append(query + h)
    return out


def pick(query, workdir, mode="long", want=6, tries=18, log=print,
         portrait_ok=False):
    """Download candidates and return the ones that fit `mode` natively.

    portrait_ok=True (biography channel): a vertical portrait is welcome even
    for a 16:9 thumbnail — the person is scaled to the frame height and the
    sides are filled with a designed gradient, so nothing is ever cut.
    """
    os.makedirs(workdir, exist_ok=True)
    # The FRAME decides the search: never ask a 16:9 thumbnail for a
    # "portrait photo" — that guarantees we only ever get vertical results.
    q0 = query
    if mode == "long":
        q0 = " ".join(w for w in query.split()
                      if w.lower() not in ("portrait", "vertical", "portrait photo"))

    seen, pool = set(), []

    def _grab(q, strict):
        for u in [u for u in search(q, log=log)][:tries]:
            if len(pool) >= want * 2:
                break
            if u in seen:
                continue
            seen.add(u)
            ext = os.path.splitext(u.split("?")[0])[1] or ".jpg"
            dest = os.path.join(workdir, "cand%02d%s" % (len(seen), ext))
            try:
                if not os.path.exists(dest):
                    download(u, dest)
            except Exception as e:
                log("[pin] skip %s" % e)
                continue
            if _fits(dest, mode, MIN_W[mode], allow_any=(not strict and portrait_ok)):
                pool.append(dest)

    # pass 1 — native orientation (landscape for 16:9, portrait for 9:16)
    for q in _queries(q0, mode):
        if len(pool) >= want:
            break
        try:
            _grab(q, strict=True)
        except Exception as e:
            log("[pin] search fail %r: %s" % (q, e))
    # pass 2 — only if the platform simply has no wide photo of this subject
    if portrait_ok and len(pool) < want:
        for uq in (q0, q0 + " photo"):
            if len(pool) >= want:
                break
            try:
                _grab(uq, strict=False)
            except Exception as e:
                log("[pin] search fail %r: %s" % (uq, e))

    ok = pool[:want]
    log("[pin] %d candidates fit %s (%d native)" % (
        len(ok), mode,
        sum(1 for p in ok if _fits(p, mode, MIN_W[mode]))))
    return ok


def _area(path):
    try:
        with Image.open(path) as im:
            return im.size[0] * im.size[1], im.size[0] / max(1, im.size[1])
    except Exception:
        return 0, 0.0


def _focus(path):
    """Cheap subject detector: where are the skin-tone pixels?

    Returns the prominence of the face/body blob (0..1). No OpenCV needed —
    a YCbCr skin mask is enough to prefer the photo where the person is big
    and centred over the one where they are a speck in the corner.
    """
    try:
        with Image.open(path) as im:
            t = im.convert("RGB")
            t.thumbnail((160, 160), Image.BILINEAR)
            w, h = t.size
            ycc = t.convert("YCbCr")
            px = list(ycc.getdata())
    except Exception:
        return 0.0
    if not px:
        return 0.0
    xs, ys, n = [], [], len(px)
    for i, (y, cb, cr) in enumerate(px):
        if y >= 60 and 77 <= cb <= 132 and 133 <= cr <= 178:
            xs.append(i % w)
            ys.append(i // w)
    frac = len(xs) / float(n)
    if frac < 0.003 or frac > 0.35:          # nothing, or false positive
        return 0.0
    xs.sort()
    ys.sort()
    x0, x1 = xs[int(len(xs) * .03)], xs[int(len(xs) * .97)]
    y0, y1 = ys[int(len(ys) * .03)], ys[int(len(ys) * .97)]
    bh = (y1 - y0) / float(h)
    bw = (x1 - x0) / float(w)
    if not (0.10 <= bh <= 0.98) or not (0.10 <= bw <= 0.98):
        return 0.0
    if bh * bw < 0.02 or bh * bw > 0.75:
        return 0.0
    # bigger blob that stays in the upper-centre (where a portrait sits) wins
    cx = ((x0 + x1) / 2.0) / w
    centre = 1.0 - min(1.0, abs(cx - 0.5) * 2.0)
    return min(1.0, bh * (0.55 + 0.45 * centre))


def rank(cands, mode, portrait_ok=False):
    """Best first: the photo that fills the most of the empty frame area
    (contain-fit coverage); inside the same coverage bucket, the one where
    the person is biggest and most centred."""
    W, H = MODES[mode]
    band = int(H * 0.20)
    aw, ah = W, H - band

    def stats(p):
        try:
            with Image.open(p) as im:
                sw, sh = im.size
        except Exception:
            return 0.0, 0, 0.0
        if not sw or not sh:
            return 0.0, 0, 0.0
        s = min(aw / float(sw), ah / float(sh))
        cov = ((sw * s) * (sh * s)) / float(aw * ah)
        return cov, sw * sh, _focus(p)

    keyed = [(stats(p), p) for p in cands]
    keyed.sort(key=lambda kp: (-round(kp[0][0] * 12),   # coverage buckets
                               -kp[0][2],               # face prominence
                               -kp[0][1]))              # resolution
    return [p for _, p in keyed]


# ------------------------------------------------------------------ compose --


def _font(size):
    for p in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _dominant(img):
    small = img.convert("RGB").resize((32, 32), Image.BILINEAR)
    px = list(small.getdata())
    n = max(1, len(px))
    return tuple(sum(c[i] for c in px) // n for i in range(3))


def accent_of(img, fallback=(255, 214, 10)):
    """Accent colour taken FROM the photo, so the headline + the glow around
    the frame harmonise with the picture instead of fighting it.

    Picks the most saturated / brightest colour with enough pixels in it
    (a red-lit face -> warm red glow, a DNA render -> cyan/violet, ...).
    """
    try:
        q = img.convert("RGB").quantize(colors=16, method=Image.MEDIANCUT)
    except Exception:                                   # noqa: BLE001
        return fallback
    pal = q.getpalette() or []
    counts = q.getcolors() or []                        # [(n, idx)]
    best, best_score = None, 0.0
    for n, idx in counts:
        i = idx * 3
        r, g, b = pal[i], pal[i + 1], pal[i + 2]
        mx, mn = max(r, g, b), min(r, g, b)
        sat = 0.0 if mx == 0 else (mx - mn) / float(mx)
        val = mx / 255.0
        if sat < 0.16 or val < 0.18:                    # skip greys / shadows
            continue
        score = n * (0.3 + sat) * (0.45 + 0.55 * val)
        if score > best_score:
            best, best_score = (r, g, b), score
    if best is None:
        # greyscale / near-mono photo (a B&W portrait, a night shot): there is
        # no colour to borrow, so take the accent from the photo's own light —
        # the brightest, slightly tinted tone — instead of a loud default.
        try:
            small = img.convert("RGB").resize((48, 48), Image.BILINEAR)
            px = list(small.getdata())
            light = sorted(px, key=lambda c: -(c[0] + c[1] + c[2]))[:max(1, len(px) // 12)]
            avg = tuple(sum(c[i] for c in light) // len(light) for i in range(3))
            mx, mn = max(avg), min(avg)
            if mx - mn < 26:                          # truly neutral
                avg = (min(255, avg[0] + 8), avg[1], min(255, avg[2] + 6))
            if max(avg) < 170:                        # keep it readable
                f = 205.0 / max(1, max(avg))
                avg = tuple(min(255, int(c * f)) for c in avg)
            return avg
        except Exception:
            return fallback
    # keep it readable as text: brighten dark accents
    if max(best) < 150:
        f = 190.0 / max(1, max(best))
        best = tuple(min(255, int(c * f)) for c in best)
    return best


def _glow(canvas, accent, strength=0.85):
    """Soft coloured rim around the frame — the 'fire' around the thumbnail,
    tinted with the photo's own accent so it reads as part of the picture."""
    from PIL import ImageChops
    W, H = canvas.size
    mask = Image.new("L", (W, H), 0)
    m = ImageDraw.Draw(mask)
    t = max(6, int(min(W, H) * 0.018))                 # rim thickness
    m.rectangle([0, 0, W - 1, H - 1], outline=255, width=t)
    mask = mask.filter(ImageFilter.GaussianBlur(t * 1.6))
    if strength != 1.0:
        mask = mask.point(lambda v: int(v * strength))
    rim = Image.new("RGB", (W, H), accent)
    out = ImageChops.screen(canvas, Image.composite(
        rim, Image.new("RGB", (W, H), (0, 0, 0)), mask))
    # thin hot core so the rim looks lit, not sprayed
    core = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(core).rectangle(
        [t // 2, t // 2, W - 1 - t // 2, H - 1 - t // 2],
        outline=tuple(min(255, int(c * 0.65 + 90)) for c in accent),
        width=max(2, t // 4))
    return ImageChops.screen(out, core)


def _dark(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c)


def _compose_bg(W, H, dom, accent):
    """Designed background for the empty side space: a vertical gradient from
    a tinted dark top to a deeper dark bottom — reads as intentional, not as
    an uncropped letterbox."""
    top = tuple(int(0.66 * dom[i] + 0.34 * accent[i]) for i in range(3))
    top = _dark(top, 0.46)
    bot = _dark(_dark(dom, 0.55), 0.55)
    img = Image.new("RGB", (1, H))
    px = img.load()
    for y in range(H):
        t = y / float(max(1, H - 1))
        px[0, y] = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    return img.resize((W, H), Image.BILINEAR)


def compose(img_path, text, out, mode="long", band_frac=0.20, accent=None,
            glow=True, sub=None, x_anchor=0.5):
    """Whole subject visible (never cropped) + headline in a slim band above
    it, so the text can never land on the person's face.

    accent/glow/band colours are derived from the photo itself.
    sub       -> optional second line (smaller), still inside the band
    x_anchor  -> 0.5 centred; 0.62 pushes a portrait to the right of the frame
    """
    W, H = MODES[mode]
    src = Image.open(img_path).convert("RGB")
    sw, sh = src.size
    band = int(H * band_frac)
    aw, ah = W, H - band

    s = min(aw / sw, ah / sh)                      # contain -> never cropped
    nw, nh = max(1, int(sw * s)), max(1, int(sh * s))
    photo = src.resize((nw, nh), Image.LANCZOS)

    dom = _dominant(src)
    if accent is None:
        accent = accent_of(src)

    canvas = _compose_bg(W, H, dom, accent)
    d = ImageDraw.Draw(canvas)
    px = int((W - nw) * x_anchor)
    canvas.paste(photo, (px, band + (ah - nh) // 2))
    d.rectangle([0, 0, W, band], fill=_dark(
        tuple(int(0.62 * dom[i] + 0.38 * accent[i]) for i in range(3)), 0.34))
    d.rectangle([0, band - 3, W, band], fill=accent)           # rule = accent

    # headline inside the band (dark plate + accent text, auto-shrunk)
    probe = ImageDraw.Draw(Image.new("L", (8, 8)))
    maxw = int(W * 0.90)
    blocks = [[(text or "").upper(), 0.44]]
    if sub:
        blocks.append([sub.upper(), 0.27])

    size = int(band * blocks[0][1])
    while size >= 20:
        f = _font(size)
        lines = _wrap(probe, blocks[0][0], f, maxw)
        extra = 0
        if sub:
            sub_size = max(14, int(size * 0.62))
            extra = _wrap(probe, blocks[1][0], _font(sub_size), maxw).__len__() \
                * int(sub_size * 1.15) + 8
        if len(lines) * int(size * 1.12) + extra <= band * 0.80:
            break
        size -= 2

    rows = []                                          # [(lines, font, lh)]
    f = _font(size)
    lh = int(size * 1.12)
    rows.append((_wrap(probe, blocks[0][0], f, maxw), f, lh))
    if sub:
        ss = max(14, int(size * 0.62))
        fs = _font(ss)
        rows.append((_wrap(probe, blocks[1][0], fs, maxw),
                     fs, int(ss * 1.15)))

    gap = max(4, size // 8)
    total = sum(len(r[0]) * r[2] + (gap if i else 0)
                for i, r in enumerate(rows))
    y = (band - total) // 2
    for i, (lns, fnt, lh_) in enumerate(rows):
        if i:
            y += gap
        colour = accent if i == 0 else tuple(
            min(255, int(c * 0.78 + 60)) for c in accent)
        for ln in lns:
            tw = int(probe.textlength(ln, font=fnt))
            bx = (W - tw) // 2
            d.rounded_rectangle([bx - 12, y - 4, bx + tw + 12, y + lh_ + 2],
                                radius=8, fill=(0, 0, 0, 225))
            d.text((bx + 2, y + 2), ln, font=fnt, fill=(0, 0, 0))   # shadow
            d.text((bx, y), ln, font=fnt, fill=colour)
            y += lh_

    if glow:
        canvas = _glow(canvas, accent)

    canvas.save(out, "JPEG", quality=94)
    try:
        src.close()
    except Exception:
        pass
    return out, accent


# ------------------------------------------------------------------ public ---


def thumbnail(query, text, out, mode="long", workdir=None, log=print,
              portrait_ok=False, sub=None, x_anchor=0.5, glow=True):
    """search -> download -> compose. Returns (path, used_source)."""
    if workdir is None:
        workdir = os.path.join(os.path.dirname(out) or ".", "_pin_cache")
    cands = pick(query, workdir, mode=mode, log=log, portrait_ok=portrait_ok)
    if not cands:
        raise RuntimeError("pinterest: no photo fits %s for %r" % (mode, query))
    ranked = rank(cands, mode, portrait_ok=portrait_ok)
    chosen = ranked[0]
    rest = ranked[1:]
    random.shuffle(rest)                # keep variety in later runs
    ranked = [chosen] + rest
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    compose(chosen, text, out, mode=mode, sub=sub, x_anchor=x_anchor,
            glow=glow)
    log("[pin] thumbnail %s  <- %s" % (os.path.basename(out),
                                       os.path.basename(chosen)))
    return out, chosen


if __name__ == "__main__":
    import sys
    q = sys.argv[1]
    t = sys.argv[2]
    o = sys.argv[3]
    m = sys.argv[4] if len(sys.argv) > 4 else "long"
    print(thumbnail(q, t, o, m)[0])
