# -*- coding: utf-8 -*-
"""Infinite biography timeline for channel 3 — 'The Reverse Timeline of Lives'.

Order of work (exactly as requested):

    1. TODAY          Elon Musk, Trump, Zuckerberg, Taylor Swift, ...
    2. LATE 20th C.   Steve Jobs, Michael Jackson, Diana, Mandela, ...
    3. 19th C.        Tesla, Edison, Darwin, Lincoln, van Gogh, ...
    4. RENAISSANCE    da Vinci, Galileo, Shakespeare, Newton, ...
    5. ANCIENT        Socrates, Plato, Aristotle, Caesar, Cleopatra, ...

When the curated names run out, the pool refills itself from Wikipedia
categories of the same era, so the content NEVER ends: there is always
another life to write.

    from life_topics import next_topic, mark_used
    topic, person, era = next_topic()
"""
from __future__ import annotations

import json
import os
import random
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "..", "state")
USED_FILE = os.path.join(STATE, "life_used.txt")
POOL_FILE = os.path.join(STATE, "life_pool.json")

# politeness / monetization filters (person names, so match on the words)
SENSITIVE = ("hitler", "stalin", "mao ", "pol pot", "bin laden", "serial killer",
             "massage parlor")

# era -> curated names, ordered modern -> ancient
CURATED = {
    "today": [
        "Elon Musk", "Donald Trump", "Mark Zuckerberg", "Jeff Bezos",
        "Bill Gates", "Jensen Huang", "Satya Nadella", "Tim Cook",
        "Warren Buffett", "Oprah Winfrey", "Taylor Swift", "Beyonce",
        "Rihanna", "Kim Kardashian", "Kanye West", "MrBeast",
        "Cristiano Ronaldo", "Lionel Messi", "LeBron James",
        "Michael Jordan", "Serena Williams", "Usain Bolt",
        "Dwayne Johnson", "Leonardo DiCaprio", "Tom Hanks",
        "Lady Gaga", "Adele", "Ed Sheeran", "Shakira", "Neymar",
        "Greta Thunberg", "Angela Merkel", "Narendra Modi",
        "Vladimir Putin", "Volodymyr Zelenskyy", "Macron",
        "Rupert Murdoch", "George Soros", "Bernard Arnault",
        "Michael Bloomberg", "Jack Ma", "Mukesh Ambani",
    ],
    "late20": [
        "Steve Jobs", "Michael Jackson", "Madonna", "Freddie Mercury",
        "Princess Diana", "Winston Churchill", "John F. Kennedy",
        "Martin Luther King", "Nelson Mandela", "Mother Teresa",
        "Muhammad Ali", "Walt Disney", "Alfred Hitchcock", "Coco Chanel",
        "Audrey Hepburn", "Marilyn Monroe", "Bob Marley", "Elvis Presley",
        "The Beatles", "Kurt Cobain", "Bob Dylan", "Andy Warhol",
        "Pablo Picasso", "Che Guevara", "Fidel Castro", "Margaret Thatcher",
        "Ronald Reagan", "Mikhail Gorbachev", "Neil Armstrong",
        "Yuri Gagarin", "Stephen Hawking", "Alan Greenspan",
        "Henry Ford", "Walt Disney", "Charlie Chaplin", "Agatha Christie",
        "J.R.R. Tolkien", "George Orwell", "Ernest Hemingway",
        "Walt Whitman", "Thomas Edison", "Nikola Tesla",
    ],
    "c19": [
        "Charles Darwin", "Albert Einstein", "Abraham Lincoln",
        "Napoleon Bonaparte", "Karl Marx", "Sigmund Freud",
        "Vincent van Gogh", "Claude Monet", "Gustave Eiffel",
        "Alexander Graham Bell", "Louis Pasteur", "Gregor Mendel",
        "Florence Nightingale", "Jane Austen", "Mary Shelley",
        "Emily Dickinson", "Mark Twain", "Charles Dickens",
        "Leo Tolstoy", "Fyodor Dostoevsky", "Anton Chekhov",
        "Friedrich Nietzsche", "Oscar Wilde", "Lewis Carroll",
        "Ludwig van Beethoven", "Frédéric Chopin", "Johannes Brahms",
        "Andrew Carnegie", "John D. Rockefeller", "J.P. Morgan",
        "Susan B. Anthony", "Harriet Tubman", "W.E.B. Du Bois",
        "Otto von Bismarck", "Simón Bolívar", "Queen Victoria",
    ],
    "renaissance": [
        "Leonardo da Vinci", "Michelangelo", "Galileo Galilei",
        "William Shakespeare", "Isaac Newton", "Nicolaus Copernicus",
        "Johannes Gutenberg", "Christopher Columbus", "Martin Luther",
        "Rembrandt", "Raphael", "Titian", "El Greco", "Velazquez",
        "Miguel de Cervantes", "John Locke", "Voltaire", "Montaigne",
        "Paracelsus", "Andreas Vesalius", "Tycho Brahe", "Johannes Kepler",
        "Edmund Halley", "Robert Hooke", "Christopher Wren",
        "Suleiman the Magnificent", "Genghis Khan", "Marco Polo",
        "Avicenna", "Averroes", "Maimonides", "Thomas Aquinas",
        "Dante Alighieri", "Petrarch", "Boccaccio",
    ],
    "ancient": [
        "Socrates", "Plato", "Aristotle", "Alexander the Great",
        "Julius Caesar", "Cleopatra", "Homer", "Archimedes",
        "Pythagoras", "Euclid", "Hippocrates", "Galen",
        "Confucius", "Laozi", "Siddhartha Gautama", "Mahavira",
        "Sun Tzu", "King Solomon", "Moses", "Cyrus the Great",
        "Darius the Great", "Hammurabi", "Ramesses the Second",
        "Akhenaten", "Nefertiti", "Gilgamesh", "Leonidas",
        "Pericles", "Herodotus", "Thucydides", "Marcus Aurelius",
        "Seneca", "Epictetus", "Virgil", "Ovid", "Cicero",
        "Augustus", "Hannibal", "Xerxes", "Athena (myth)",
        "Sappho", "Aspasia", "Hypatia", "Aesop",
    ],
}

ERA_ORDER = ["today", "late20", "c19", "renaissance", "ancient"]

# Wikipedia categories used to top the pool up forever, per era
ERA_CATS = {
    "today": ["21st-century American businesspeople",
              "21st-century American singers", "Living people",
              "21st-century American actors"],
    "late20": ["20th-century American businesspeople",
               "20th-century American singers",
               "20th-century American politicians"],
    "c19": ["19th-century American businesspeople",
            "19th-century English writers", "19th-century scientists"],
    "renaissance": ["16th-century Italian painters",
                    "17th-century English writers",
                    "15th-century Italian people"],
    "ancient": ["Ancient Greek philosophers", "Ancient Roman politicians",
                "Ancient Egyptian pharaohs", "Ancient Greek generals"],
}


# ------------------------------------------------------------------ state ---

def _used():
    if not os.path.exists(USED_FILE):
        return set()
    return set(x.strip() for x in
               open(USED_FILE, encoding="utf-8").read().splitlines() if x.strip())


def mark_used(name):
    os.makedirs(STATE, exist_ok=True)
    with open(USED_FILE, "a", encoding="utf-8") as f:
        f.write(name.strip() + "\n")


def _load_pool():
    if os.path.exists(POOL_FILE):
        try:
            return json.load(open(POOL_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_pool(pool):
    os.makedirs(STATE, exist_ok=True)
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=1)


def _bad(name):
    low = name.lower()
    if len(name.split()) > 5 or len(name) < 4:
        return True
    return any(s in low for s in SENSITIVE)


# ------------------------------------------------------------- wikipedia ----

def _wiki(category, limit=400):
    """Free, no key: members of an English Wikipedia category."""
    url = ("https://en.wikipedia.org/w/api.php?action=query&list=categorymembers"
           "&cmtitle=" + urllib.parse.quote("Category:" + category) +
           "&cmtype=page&cmlimit=%d&format=json" % limit)
    req = urllib.request.Request(url, headers={"User-Agent": "yt-bio/1.0"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=25))
    except Exception:
        return []
    out = []
    for m in data.get("query", {}).get("categorymembers", []):
        t = m.get("title", "").replace(" (disambiguation)", "")
        if t and not _bad(t):
            out.append(t)
    random.shuffle(out)
    return out


def _refill(era, need=120):
    """Grow this era's pool from Wikipedia until it has `need` fresh names."""
    pool = _load_pool()
    have = set(pool.get(era, [])) | _used()
    fresh = [n for n in pool.get(era, []) if n not in have]
    if len(fresh) >= need // 2:
        return pool
    for cat in ERA_CATS.get(era, []):
        for n in _wiki(cat):
            if n not in have and not _bad(n):
                pool.setdefault(era, []).append(n)
                have.add(n)
        if len([n for n in pool.get(era, []) if n not in _used()]) >= need:
            break
    _save_pool(pool)
    return pool


# ---------------------------------------------------------------- public ----

def next_topic():
    """Next unused life, modern era first, then older. Returns
    (topic_sentence, person_name, era). Never runs out."""
    used = _used()
    pool = _load_pool()

    for era in ERA_ORDER:
        names = list(CURATED.get(era, [])) + list(pool.get(era, []))
        fresh = [n for n in names if n not in used and not _bad(n)]
        if not fresh:
            pool = _refill(era)
            names = list(CURATED.get(era, [])) + list(pool.get(era, []))
            fresh = [n for n in names if n not in used and not _bad(n)]
        if not fresh:
            continue
        person = fresh[0]                    # deterministic order per era
        mark_used(person)
        return _sentence(person), person, era

    # every era exhausted -> keep refilling the newest one (never happens in
    # practice, but the pool is designed to be endless)
    pool = _refill("today", need=600)
    fresh = [n for n in pool.get("today", []) if n not in _used() and not _bad(n)]
    person = fresh[0] if fresh else "Elon Musk"
    mark_used(person)
    return _sentence(person), person, "today"


def _sentence(person):
    return (f"{person}, told backwards: the decisions and reversals that made "
            f"{person} inevitable, walked from the present moment back to the "
            f"origin story nobody remembers")


if __name__ == "__main__":
    for _ in range(6):
        t, p, e = next_topic()
        print("%-8s %-24s %s" % (e, p, t[:70]))
