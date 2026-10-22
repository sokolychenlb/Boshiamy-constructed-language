"""Cached, rate-limited public Boshiamy and Kaikki/Wiktionary lookups."""

import hashlib
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pos_classifier import classify, classify_detail, load_wordnet, WORDNET_URL, WORDNET_LICENSE


class Elements(HTMLParser):
    """Collect complete selected elements without reading scripts as dictionary text."""

    def __init__(self, tag, predicate=lambda attrs: True):
        super().__init__(convert_charrefs=True)
        self.tag, self.predicate = tag, predicate
        self.depth = 0
        self.parts = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += 1
        elif tag == self.tag and self.predicate(dict(attrs)):
            self.depth = 1
            self.parts = []

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1
            if not self.depth:
                self.items.append("".join(self.parts))

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


class Fetcher:
    def __init__(self, cache, delay=1.0, refresh=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.delay, self.refresh = delay, refresh
        self.last_request = 0.0

    def get(self, url, binary=False):
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + (".bin" if binary else ".html"))
        if path.exists() and not self.refresh:
            return path.read_bytes() if binary else path.read_text(encoding="utf-8")
        for attempt in range(3):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
            try:
                request = Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; BoshiamyConlang/1.0; dictionary research)",
                    "Accept": "text/html",
                })
                self.last_request = time.monotonic()
                with urlopen(request, timeout=45) as response:
                    data = response.read()
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(data)
                temporary.replace(path)
                return data if binary else data.decode("utf-8")
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise ValueError(f"HTTP {exc.code}: {url}") from exc
                retry = exc.headers.get("Retry-After", "")
                if retry.isdigit() and int(retry) > 60:
                    raise ValueError(f"Server requests a {retry}s pause; retry later: {url}") from exc
                time.sleep(max(2 ** (attempt + 1), int(retry) if retry.isdigit() else 0))
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise ValueError(f"Network failure: {url}: {exc}") from exc
                time.sleep(2 ** (attempt + 1))


def parse_codes(text, character):
    # Restrict parsing to the character's result block, excluding help examples.
    cards = Elements("div", lambda a: "text-6xl" in a.get("class", "").split())
    cards.feed(text)
    if cards.items != [character]:
        raise ValueError(f"Unexpected code lookup results for {character!r}; website format may have changed")
    spans = Elements("span", lambda a: {"font-mono", "tracking-widest"}.issubset(a.get("class", "").split()))
    spans.feed(text)
    codes = list(dict.fromkeys(s.strip() for s in spans.items if re.fullmatch(r"[A-Z]{1,4}", s.strip())))
    if not codes:
        raise ValueError(f"No eligible 1–4-letter codes for {character!r}")
    return " ".join(codes)


def parse_entries(text, character):
    blocks = Elements("pre")
    blocks.feed(text)
    decoder = json.JSONDecoder()
    entries = []
    for block in blocks.items:
        remaining = block.strip()
        while remaining:
            try:
                entry, end = decoder.raw_decode(remaining)
            except json.JSONDecodeError:
                break  # Other preformatted blocks contain extraction diagnostics.
            if isinstance(entry, dict) and entry.get("word") == character and entry.get("lang_code") == "zh":
                entries.append(entry)
            remaining = remaining[end:].lstrip()
    if not entries:
        raise ValueError(f"No structured Chinese dictionary entries for {character!r}")
    return entries


def fetch_rows(characters, cache, all_senses=False, refresh=False, delay=1.0):
    fetcher = Fetcher(cache, delay, refresh)
    load_wordnet(fetcher)
    rows, audit, failures = [], [], []
    for character in dict.fromkeys(characters):
        if character.isspace():
            continue
        if not re.fullmatch(r"[\u3400-\u9fff\uf900-\ufaff\U00020000-\U000323af]", character):
            failures.append({"character": character, "error": "Not a supported Han character"})
            continue
        code_url = "https://boshiamy.then.tw/query/" + quote(character, safe="")
        dictionary_url = "https://kaikki.org/dictionary/Chinese/meaning/" + quote(
            f"{character}/{character}/{character}.html", safe="/"
        )
        try:
            codes = parse_codes(fetcher.get(code_url), character)
            entries = parse_entries(fetcher.get(dictionary_url), character)
            found = []
            seen = set()
            for entry in entries:
                if entry.get("pos") == "soft-redirect":
                    continue
                for sense in entry.get("senses", []):
                    glosses = sense.get("glosses", [])
                    if not glosses or "no-gloss" in sense.get("tags", []):
                        continue
                    gloss = glosses[-1].strip()
                    if not gloss or sense.get("form_of") or sense.get("alt_of"):
                        continue
                    classification = classify_detail(entry, sense, gloss)
                    pos = classification["pos"]
                    if (gloss, pos) in seen:
                        continue
                    seen.add((gloss, pos))
                    found.append((gloss, classification))
            if not found:
                raise ValueError("No usable non-redirect dictionary senses")
            if not all_senses:
                found = found[:1]
            for gloss, classification in found:
                pos = classification["pos"]
                rows.append(dict(character=character, meaning=gloss, pos=pos, codes=codes))
                audit.append(dict(character=character, meaning=gloss, **classification,
                                  codes_url=code_url, dictionary_url=dictionary_url,
                                  wiktionary_url="https://en.wiktionary.org/wiki/" + quote(character)))
            print(f"Fetched U+{ord(character):04X}: {len(found)} sense(s)")
        except ValueError as exc:
            failures.append({"character": character, "error": str(exc)})
    return rows, {"entries": audit, "failures": failures,
                  "pos_resource": WORDNET_URL, "pos_resource_license": WORDNET_LICENSE,
                  "attribution": "Definitions adapted from English Wiktionary via Kaikki.org / Wiktextract.",
                  "license": "https://creativecommons.org/licenses/by-sa/4.0/",
                  "license_note": "Retain attribution and applicable share-alike terms when redistributing definitions."}
