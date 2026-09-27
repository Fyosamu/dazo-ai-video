# -*- coding: utf-8 -*-
"""Channel 3 — 'The Reverse Timeline of Lives' (biography docs).
Same pipeline/format as channel 1 (Emma voice 0.95, rounded subtitles,
cinematic intro on long, hook-first short), only the content layer differs.
Outputs go to Desktop\\life_sample (next to the chess sample).
"""
import os
import sys

os.environ.setdefault("MPT_OUT_DIR", os.path.join(os.path.expanduser("~"), "Desktop", "yt_final"))
os.environ.setdefault("MPT_COPY_PROJECT", "0")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import make_sample as base  # noqa: E402  (env must be set before import)

# --------------------------------------------------- infinite life timeline ----
# Modern faces first (Musk, Trump, today's stars) -> 20th century -> 19th ->
# Renaissance -> Ancient (Socrates, Caesar, ...). The pool refills itself from
# Wikipedia categories, so the channel NEVER runs out of lives to tell.
import life_topics  # noqa: E402

_LIFE = None


def _next_life():
    """Pop the next unused person (only once per run)."""
    global _LIFE
    if _LIFE is None:
        _LIFE = life_topics.next_topic()
    return _LIFE


_P = "Taylor Swift"
if os.environ.get("MPT_TOPIC"):
    base.TOPIC = os.environ["MPT_TOPIC"]
    _P = base.TOPIC.split(", told backwards")[0].strip() or base.TOPIC
    _LIFE = (base.TOPIC, _P, "manual")
else:
    _T, _P, _E = _next_life()
    base.TOPIC = _T
    print(f"[life] era={_E}  person={_P}", flush=True)

# thumbnail headline: exactly what was asked — "MY LIFE?" (person named below it)
base.THUMB_TEXT = os.environ.get("MPT_THUMB") or "MY LIFE?"


def _life_thumbnail(topic: str, text: str, dest):
    """Pinterest portrait of the person + headline in a band ABOVE the face."""
    person = (_P if _LIFE and topic == base.TOPIC
              else str(topic).split(", told backwards")[0]).strip() or str(topic)
    try:
        import pin_lib
        out, _ = pin_lib.thumbnail(
            f"{person} portrait photo", text, str(dest), mode="long",
            portrait_ok=True, sub=person, x_anchor=0.60, glow=True,
            workdir=str(dest).rsplit(os.sep, 1)[0] + os.sep + "_pin_cache")
        print(f"[life] pin thumb {dest} <- {person}", flush=True)
        return dest
    except Exception as e:  # never kill the render over a thumbnail
        print(f"[life] pin thumb FAILED ({e}) — falling back", flush=True)
        return base.botlib.make_thumbnail(topic, text, dest)


# same hook for the short poster (9:16) — face fully visible, text on top
def _life_thumb_short(topic: str, text: str, dest):
    person = (_P if _LIFE and topic == base.TOPIC
              else str(topic).split(", told backwards")[0]).strip() or str(topic)
    try:
        import pin_lib
        pin_lib.thumbnail(f"{person} portrait photo", text, str(dest),
                          mode="short", portrait_ok=True, sub=person,
                          x_anchor=0.50, glow=True,
                          workdir=str(dest).rsplit(os.sep, 1)[0] + os.sep + "_pin_cache")
        return dest
    except Exception as e:
        print(f"[life] short pin failed ({e})", flush=True)
        return dest


base.botlib.make_thumbnail = _life_thumbnail

# 4 narrative frames — biography edition (rotated every episode)
base.FRAMES = [
    "Structure: cold-open with the single strangest fact about this life, "
    "then walk BACKWARD through the decisions that made it inevitable, "
    "ending on the moment everything could have gone the other way.",
    "Structure: start at the peak of their fame, strip away the legend layer "
    "by layer, and reveal the ordinary human origin underneath, closing on a "
    "question about what history will call them in100 years.",
    "Structure: open with the moment they were rejected or forgotten, jump to "
    "what they became, then trace the exact chain of cause-and-effect between "
    "the two, ending on the lesson nobody teaches.",
    "Structure: hold one object, letter or decision at the center of the life, "
    "circle it three times from different decades, then show how that one thing "
    "changed the era around them.",
]

BASE_SCRIPT_RULES = """
- Everything in English, spoken style, natural and captivating, for adults.
- Open with a strong curiosity hook that restates who this person is in sentence1.
- Then flow through clear sections WITHOUT labels, markdown or timestamps.
- NATURAL PAUSES: one blank line between sections, and occasionally before a
  revelation or after a surprising fact (a blank line every3-5 sentences, NEVER
  on every sentence). Blank lines become ~1 second breathing pauses.
- Concrete details, small surprises, psychology and historical cause-and-effect.
- End with a thought-provoking closing line and a soft subscribe ask.
- Output ONLY the narration text, plain, no headings, no asterisks."""


def build_script() -> str:
    import random
    frame = random.choice(base.FRAMES)
    lo, hi = random.choice([(1650, 2000), (2400, 2850)])
    prompt = f"""Write the full narration script for a YouTube biography documentary.
CHANNEL STYLE: biographies of famous AND forgotten figures, told in a way that
walks backward through time. TOPIC: {base.TOPIC}
REQUIREMENTS:
- Length: between {lo} and {hi} words (spoken at ~145 words/minute).
  Never below {lo}, never above {hi}.
- {frame}
- Factual, respectful, cinematic; answer "why" and "how" to the root.
{BASE_SCRIPT_RULES}"""
    script = base.gemini(prompt, max_tokens=8192)
    words = len(script.split())
    print(f"[script] {words} words (~{words/145:.1f} min)", flush=True)
    return script


def build_metadata(script: str) -> dict:
    import re
    import random
    style = random.choice(base.TITLE_STYLES)
    dtpl = random.choice(base.DESC_TEMPLATES)
    prompt = f"""For a YouTube biography video, return STRICT JSON with keys:
"title" (<=70 chars, {style}, curiosity hook, no quotes inside),
"hook" (<=6 words, punchy, UPPERCASE-able, for thumbnail overlay),
"caption" (3-4 sentences that make someone say "oh really?", English),
"description" (YouTube description: {dtpl}),
"hashtags" (array of 7 strings WITHOUT the # sign, biography/history documentary style).
TOPIC: {base.TOPIC}
SCRIPT:\n{script[:6000]}"""
    meta = base.gemini_json(prompt, max_tokens=3072)
    for k in ("title", "hook", "caption", "description"):
        meta[k] = str(meta.get(k) or "").strip()
    meta["hashtags"] = [str(h).lstrip("#") for h in (meta.get("hashtags") or [])][:8]
    print(f"[meta] {meta['title']}", flush=True)
    return meta


# install overrides before running the shared pipeline
base.build_script = build_script
base.build_metadata = build_metadata

if __name__ == "__main__":
    base.main()
