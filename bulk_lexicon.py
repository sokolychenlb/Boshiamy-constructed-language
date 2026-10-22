"""Discover Then.TW's Chinese inventory and join bulk English dictionaries."""

import gzip
import io
import json
import re
import unicodedata
import zipfile
from urllib.parse import urljoin

from fetch_lexicon import Fetcher
from pos_classifier import classify_detail, load_wordnet, WORDNET_URL, WORDNET_LICENSE

SITE = "https://boshiamy.then.tw/"
UNIHAN = "https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip"
CEDICT = "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"


def is_han(character):
    return len(character) == 1 and unicodedata.name(character, "").startswith(
        ("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-"))


def parse_table(text):
    """Read flat numeric code maps as data; never execute downloaded JavaScript."""
    result = {}
    pattern = r'("(?:[^"\\]|\\.)*"|[^\s{},:;=]+)\s*:\s*\{([^{}]*)\}'
    for match in re.finditer(pattern, text):
        key, body = match.groups()
        character = json.loads(key) if key.startswith('"') else key
        if not is_han(character):
            continue
        codes = []
        # Code selection numbers are metadata values, not part of the root.
        for item in re.finditer(r'(?:^|,)\s*("(?:[^"\\]|\\.)*"|[^,:\s]+)\s*:\s*\d+\s*(?=,|$)', body):
            code = item[1]
            code = json.loads(code) if code.startswith('"') else code
            if re.fullmatch(r"[A-Z]{1,4}", code):
                codes.append(code)
        result[character] = list(dict.fromkeys(codes))
    if not result:
        raise ValueError("No Han character maps found; Boshiamy table format may have changed")
    return result


def discover(fetcher):
    home = fetcher.get(SITE)
    scripts = list(dict.fromkeys(re.findall(r'(?:src|href)="([^"\s]+\.js)"', home)))
    loader = None
    for path in scripts:
        if not path.startswith("/_nuxt/"):
            continue
        text = fetcher.get(urljoin(SITE, path))
        if 'case"tc"' in text and 'case"ext"' in text:
            loader = (urljoin(SITE, path), text)
            break
    if loader is None:
        raise ValueError("Cannot discover Boshiamy's table loader; website format may have changed")
    assets = dict(re.findall(r'case"(tc|sc|ct|ext)".*?import\("(\./[^"\s]+\.js)"\)', loader[1]))
    if set(assets) != {"tc", "sc", "ct", "ext"}:
        raise ValueError("Cannot discover all four Chinese code tables")
    inventory, urls = {}, []
    for mode in ("tc", "ext"):
        url = urljoin(loader[0], assets[mode])
        urls.append(url)
        table = parse_table(fetcher.get(url))
        print(f"Loaded {mode} table: {len(table):,} Han characters", flush=True)
        for character, codes in table.items():
            existing = inventory.setdefault(character, [])
            existing.extend(c for c in codes if c not in existing)
    return dict(sorted(inventory.items(), key=lambda pair: ord(pair[0]))), urls


def read_cedict(data, traditional_only=True):
    meanings = {}
    for line in gzip.decompress(data).decode("utf-8-sig").splitlines():
        if line.startswith("#"):
            continue
        match = re.fullmatch(r"(\S+) (\S+) \[[^\]]+\] /(.+)/", line)
        if not match:
            continue
        traditional, simplified, definitions = match.groups()
        glosses = [g.strip() for g in definitions.split("/") if g.strip() and not re.match(
            r"(?:CL:|variant of |old variant of |see |also written |same as )", g)]
        for character in dict.fromkeys((traditional,) if traditional_only else (traditional, simplified)):
            if is_han(character):
                target = meanings.setdefault(character, [])
                target.extend(g for g in glosses if g not in target)
    if not meanings:
        raise ValueError("CC-CEDICT download contained no single-character definitions")
    return meanings


def taiwan_filter(inventory, cedict_data, unihan_data):
    """Exclude simplified-only forms, preserving independently traditional forms.

    A character occurring in a traditional CC-CEDICT headword is evidence of
    traditional use (e.g. 后 in 皇后), even if it also simplifies another character.
    """
    traditional_usage = set()
    variants = {}
    for line in gzip.decompress(cedict_data).decode("utf-8-sig").splitlines():
        match = re.match(r"(\S+) (\S+) \[", line)
        if not match:
            continue
        traditional, simplified = match.groups()
        traditional_usage.update(traditional)
        if len(traditional) == len(simplified) == 1 and traditional != simplified:
            variants.setdefault(simplified, set()).add(traditional)
    with zipfile.ZipFile(io.BytesIO(unihan_data)) as archive:
        with archive.open("Unihan_Variants.txt") as stream:
            for line in io.TextIOWrapper(stream, encoding="utf-8-sig"):
                fields = line.rstrip("\r\n").split("\t", 2)
                if len(fields) != 3 or fields[1] != "kTraditionalVariant":
                    continue
                character = chr(int(fields[0][2:], 16))
                targets = {chr(int(code, 16)) for code in re.findall(r"U\+([0-9A-F]+)", fields[2])}
                variants.setdefault(character, set()).update(targets - {character})
    excluded = []
    retained = {}
    for character, codes in inventory.items():
        if variants.get(character) and character not in traditional_usage:
            excluded.append(dict(character=character, reason="Simplified form with traditional counterparts and no traditional-headword evidence",
                                 traditional_counterparts=sorted(variants[character])))
        else:
            retained[character] = codes
    return retained, excluded


def read_unihan(data):
    definitions = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        with archive.open("Unihan_Readings.txt") as stream:
            for line in io.TextIOWrapper(stream, encoding="utf-8-sig"):
                fields = line.rstrip("\r\n").split("\t", 2)
                if len(fields) == 3 and fields[1] == "kDefinition":
                    definitions[chr(int(fields[0][2:], 16))] = fields[2]
    if not definitions:
        raise ValueError("Unihan download contained no kDefinition entries")
    return definitions


def fetch_full_rows(cache, all_senses=False, refresh=False):
    fetcher = Fetcher(cache, refresh=refresh)
    inventory, table_urls = discover(fetcher)
    print(f"Discovered {len(inventory):,} distinct Han characters; loading bulk meanings", flush=True)
    cedict_data = fetcher.get(CEDICT, binary=True)
    unihan_data = fetcher.get(UNIHAN, binary=True)
    discovered = len(inventory)
    inventory, excluded = taiwan_filter(inventory, cedict_data, unihan_data)
    print(f"Taiwan traditional filter: {len(inventory):,} retained; {len(excluded):,} simplified-only forms excluded", flush=True)
    cedict = read_cedict(cedict_data)
    unihan = read_unihan(unihan_data)
    load_wordnet(fetcher)
    rows, entries, failures = [], [], []
    for character, codes in inventory.items():
        if not codes:
            failures.append(dict(character=character, error="No eligible 1–4-letter code"))
            continue
        glosses = cedict.get(character)
        source = CEDICT
        if not glosses:
            source = UNIHAN
            definition = unihan.get(character)
            glosses = definition.split(";") if definition else []
        if not glosses:
            failures.append(dict(character=character, error="No English meaning in CC-CEDICT or Unihan"))
            continue
        if not all_senses:
            glosses = glosses[:1]
        for gloss in dict.fromkeys(g.strip() for g in glosses if g.strip()):
            classification = classify_detail({}, {}, gloss)
            pos = classification["pos"]
            rows.append(dict(character=character, meaning=gloss, pos=pos, codes=" ".join(codes)))
            entries.append(dict(character=character, meaning=gloss, **classification,
                                codes_url=SITE + "query/" + character, dictionary_url=source))
    audit = dict(entries=entries, failures=failures, discovered_characters=len(inventory),
                 before_traditional_filter=discovered, excluded_simplified_characters=excluded,
                 discovery_scope="Then.TW Taiwan traditional (tc) and rare (ext) tables; simplified-only forms filtered using CC-CEDICT and Unihan",
                 code_table_urls=table_urls,
                 pos_resource=WORDNET_URL, pos_resource_license=WORDNET_LICENSE,
                 attribution="English glosses adapted from CC-CEDICT (MDBG), with Unicode Unihan kDefinition fallback.",
                 licenses={"CC-CEDICT": "https://creativecommons.org/licenses/by-sa/4.0/",
                           "Unihan": "https://www.unicode.org/license.txt"},
                 coverage_note="All discovered characters are attempted. Missing codes/meanings and capacity failures are reported, not invented.")
    return rows, audit
