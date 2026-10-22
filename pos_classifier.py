"""Sense-level POS decisions with evidence, confidence, and explicit uncertainty."""

import io
import re
import zipfile
from collections import Counter, defaultdict

WORDNET_URL = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/wordnet.zip"
WORDNET_LICENSE = "https://wordnet.princeton.edu/license-and-commercial-use"
WORDNET = None
COARSE = {"noun": "noun", "proper noun": "noun", "verb": "verb"}
ALIASES = {"n": "noun", "n.": "noun", "name": "proper noun", "proper-noun": "proper noun",
           "v": "verb", "v.": "verb", "adj": "adjective", "adj.": "adjective",
           "adv": "adverb", "adv.": "adverb", "pron": "pronoun", "pron.": "pronoun",
           "prep": "preposition", "conj": "conjunction", "intj": "interjection",
           "num": "numeral", "det": "determiner"}
LABELS = {"noun", "proper noun", "verb", "adjective", "adverb", "pronoun", "particle",
          "preposition", "postposition", "conjunction", "interjection", "numeral",
          "determiner", "classifier", "prefix", "suffix", "auxiliary", "specifier"}
FUNCTION_WORDS = {
    "pronoun": "i me my mine we us our ours you your yours he him his she her hers it its they them their theirs myself yourself himself herself itself ourselves yourselves themselves who whom whose what which".split(),
    "determiner": "this these that those each every either neither another other some any all both many much few several".split(),
    "adverb": "not never always often sometimes seldom already still also too very quite rather extremely really truly greatly freely fully then thus here there now today yesterday tomorrow how why when where".split(),
    "conjunction": "and or but if although though because unless whereas whether".split(),
    "preposition": "of with without from into onto during despite among between through towards toward".split(),
    "interjection": ["hello", "hi", "hey", "oh", "ah", "alas", "ouch", "wow", "yes", "no", "all right!"],
    "numeral": "zero one two three four five six seven eight nine ten hundred thousand million billion first second third fourth fifth".split(),
}
# Conventional adjective glosses; decisions remain heuristic, not source labels.
ADJECTIVES = set("big small large little great good bad red blue green yellow white black purple orange pink brown gray grey beautiful ugly tall short long wide narrow deep shallow high low hot cold warm cool old young new ancient modern happy sad angry glad hungry thirsty full empty rich poor expensive cheap easy difficult hard soft dry wet clean dirty true false correct wrong appropriate proper harmonious popular revolutionary dense eldest older younger close intimate sick healthy fast slow quick quiet loud bright dark heavy light strong weak sweet bitter sour salty fresh ripe raw cooked alive dead similar different equal common rare important necessary possible impossible excellent fine nice lovely brilliant splendid".split())


class WordNetIndex:
    """Use WordNet's lemma indexes and tagged sense counts, without NLTK."""

    def __init__(self, data):
        self.parts = defaultdict(set)
        self.counts = defaultdict(Counter)
        mapping = {"noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb"}
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.license = archive.read("wordnet/LICENSE").decode("utf-8")
            for suffix, pos in mapping.items():
                for line in archive.read("wordnet/index." + suffix).decode("utf-8").splitlines():
                    if line and not line.startswith(" "):
                        self.parts[line.split()[0].replace("_", " ")].add(pos)
            types = {"1": "noun", "2": "verb", "3": "adjective", "4": "adverb", "5": "adjective"}
            for line in archive.read("wordnet/index.sense").decode("utf-8").splitlines():
                key, _, _, count = line.split()
                lemma, identifier = key.split("%", 1)
                self.counts[lemma.replace("_", " ")][types[identifier[0]]] += int(count)


def load_wordnet(fetcher):
    global WORDNET
    if WORDNET is None:
        WORDNET = WordNetIndex(fetcher.get(WORDNET_URL, binary=True))
        (fetcher.cache / "WORDNET_LICENSE.txt").write_text(WORDNET.license, encoding="utf-8")


def decision(detailed, basis, confidence="high", review=False):
    return dict(pos=COARSE.get(detailed, "other"), detailed_pos=detailed, pos_basis=basis,
                pos_confidence=confidence, pos_review_required=review)


def lexical(text):
    if text in ADJECTIVES:
        return decision("adjective", "heuristic: conventional adjective gloss", "medium", True)
    for pos, words in FUNCTION_WORDS.items():
        if text in words:
            return decision(pos, "heuristic: English function-word gloss", "medium", True)
    if WORDNET is None:
        return None
    parts = WORDNET.parts.get(text, set())
    if len(parts) == 1:
        return decision(next(iter(parts)), "WordNet: unambiguous English lemma POS", "medium", True)
    counts = WORDNET.counts.get(text, Counter()).most_common()
    if counts and counts[0][1] >= 2 and (len(counts) == 1 or counts[0][1] >= 3 * counts[1][1]):
        return decision(counts[0][0], "heuristic: dominant WordNet tagged-sense frequency", "medium", True)
    if parts == {"noun", "verb"}:
        return decision("noun", "heuristic: bare noun/verb lemma; dictionary infinitives normally use 'to'", "low", True)
    return None


def classify_detail(entry, sense, gloss):
    # Sense-level labels take precedence over generic entry headings.
    for raw in (sense.get("pos", ""), *sense.get("tags", []), entry.get("pos", "")):
        label = ALIASES.get(raw.lower(), raw.lower())
        if label in LABELS:
            return decision(label, "dictionary POS: " + label)
    categories = sense.get("categories", [])
    names = [c.get("name", "") if isinstance(c, dict) else str(c) for c in categories]
    for name in names:
        match = re.search(r"(?:Chinese|Mandarin) (nouns|verbs|adjectives|adverbs|pronouns|particles|classifiers)\b", name)
        if match:
            return decision(match[1][:-1], "dictionary sense category: " + name)
    text = gloss.strip().lower()
    # Recognize actual grammatical annotations, not incidental words in a noun definition.
    annotations = " ".join(re.findall(r"\(([^()]*)\)", text))
    for label in ("particle", "pronoun", "adjective", "adverb", "preposition", "conjunction",
                  "interjection", "classifier", "determiner", "numeral", "specifier", "auxiliary"):
        if re.search(r"\b" + label + r"\b", annotations) and not re.search(r"\b(?:before|after|followed by|modifies)\b", annotations):
            return decision(label, "explicit grammatical annotation: " + label)
    if re.match(r"^(?:a |an )?(?:sentence[- ]final |question |modal |aspect |possessive |discourse )?particle\b", text):
        return decision("particle", "explicit particle definition")
    if re.match(r"^(?:classifier|measure word) (?:for|used)\b", text):
        return decision("classifier", "explicit classifier definition")
    if re.match(r"^(?:used |indicat|express|mark|grammatical|verb complement|also pr\.|taiwan pr\.)", text):
        return decision("unknown", "grammatical/usage note: no lexical noun sense established", "low", True)
    if re.search(r"^\((?:used |before |after |also,|verb complement)", text):
        return decision("particle", "heuristic: grammatical-function description", "medium", True)
    # Remove nested parenthetical usage notes without losing the gloss outside them.
    bare = text
    while re.search(r"\([^()]*\)", bare):
        bare = re.sub(r"\([^()]*\)", " ", bare)
    bare = re.sub(r"\s+", " ", bare).strip()
    if bare.startswith("surname "):
        return decision("proper noun", "explicit surname definition")
    # 'to be happy' is an adjective gloss; 'to be fond of' is treated similarly.
    if bare.startswith("to be "):
        complement = bare[6:].split(";", 1)[0].strip()
        head = complement.split(" ", 1)[0]
        if head in ADJECTIVES or head in {"fond", "prone", "able", "unable", "afraid", "aware"}:
            return decision("adjective", "heuristic: copular adjective gloss", "medium", True)
        evidence = lexical(complement)
        if evidence and evidence["detailed_pos"] == "adjective":
            return evidence
    if bare.startswith("to "):
        return decision("verb", "heuristic: English infinitive gloss", "medium", True)
    if bare.split(" ", 1)[0] in ADJECTIVES and re.match(r"^\S+ (?:to|of|with|for|than|enough)\b", bare):
        return decision("adjective", "heuristic: adjective with complement", "medium", True)
    chunks = [part.strip() for part in re.split(r"[;,]", bare) if part.strip()]
    evidence = [lexical(chunk) for chunk in chunks]
    known = [item for item in evidence if item]
    if known and len(known) == len(chunks) and len({item["detailed_pos"] for item in known}) == 1:
        return known[0]
    if bare.startswith(("a ", "an ", "the ")):
        return decision("noun", "heuristic: English noun phrase with article", "medium", True)
    if WORDNET and len(chunks) > 1:
        sets = [WORDNET.parts.get(chunk, set()) for chunk in chunks]
        common = set.intersection(*sets) if all(sets) else set()
        if len(common) == 1:
            return decision(next(iter(common)), "WordNet: shared POS across synonym glosses", "medium", True)
    if WORDNET and len(chunks) == 1:
        words = bare.split()
        if 1 < len(words) <= 5:
            head = lexical(words[-1])
            modifiers = words[:-1]
            if head and head["pos"] == "noun" and all(
                word in ADJECTIVES or "adjective" in WORDNET.parts.get(word, set()) for word in modifiers
            ):
                return decision("noun", "heuristic: adjective modifiers plus WordNet noun head", "medium", True)
    # Pronouns often have explanatory tails, e.g. 'you (informal)' or 'that ...'.
    if len(chunks) == 1 and bare in FUNCTION_WORDS["pronoun"] + FUNCTION_WORDS["determiner"]:
        return lexical(bare)
    return decision("unknown", "Unresolved/ambiguous gloss; assigned other (u), not a noun", "low", True)


def classify(entry, sense, gloss):
    result = classify_detail(entry, sense, gloss)
    return result["pos"], result["pos_basis"]
