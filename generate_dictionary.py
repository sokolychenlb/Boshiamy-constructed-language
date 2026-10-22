"""Generate a four-column constructed-language dictionary (Python 3.10+)."""

import argparse
import csv
from collections import Counter
import itertools
import json
import random
import re
from pathlib import Path

ORTHOGRAPHY = dict(zip("abcdefghijklmnopqrstuvwxyz", "ǧbšdžfghħ’klmnṯpqrstḏvřxʿz"))
IPA = dict(zip("abcdefghijklmnopqrstuvwxyz", "ɣbʃdʒfghħʔklmnθpqrstðvʀxʕz"))
FIRST_VOWEL = {"noun": "i", "verb": "a", "other": "u"}
VOWELS = "aiu"


def shortest_code(raw: str) -> str:
    """Codes separated by whitespace, commas, pipes, or semicolons; ties keep order.

    One-letter shortcuts are ineligible. Selection digits and punctuation are
    rejected rather than silently interpreted as consonants.
    """
    codes = re.split(r"[\s,;|]+", raw.strip().lower())
    if not codes or any(not re.fullmatch(r"[a-z]{1,4}", c) for c in codes):
        raise ValueError(f"Invalid code list: {raw!r}; use 1–4 ASCII letters per code")
    eligible = [c for c in codes if 2 <= len(c) <= 4]
    if not eligible:
        raise ValueError(f"No eligible 2–4-letter code in {raw!r}")
    return min(eligible, key=len)


def candidates(code: str, pos: str):
    """Enumerate CV…CVC and CV…CV, each with the required first vowel."""
    for final_coda in (True, False):
        vowel_count = len(code) - int(final_coda)
        for rest in itertools.product(VOWELS, repeat=vowel_count - 1):
            vowels = (FIRST_VOWEL[pos],) + rest
            orth, ipa = [], []
            for index, consonant in enumerate(code):
                orth.append(ORTHOGRAPHY[consonant])
                ipa.append(IPA[consonant])
                if index < vowel_count:
                    orth.append(vowels[index])
                    ipa.append(vowels[index])
            yield "".join(orth), "".join(ipa)


def generate(rows, seed=0, rejected=None):
    rng = random.Random(seed)
    used = set()
    seen = set()
    result = []
    for line, row in enumerate(rows, start=2):
        try:
            character = row["character"].strip()
            meaning = row["meaning"].strip()
            pos = row["pos"].strip().lower()
            if len(character) != 1 or not meaning:
                raise ValueError("character must be one character and meaning must be nonempty")
            if pos not in FIRST_VOWEL:
                raise ValueError("pos must be noun, verb, or other")
            code = shortest_code(row["codes"])
            identity = (character, meaning, pos, code)
            if identity in seen:
                continue
            seen.add(identity)
            options = list(candidates(code, pos))
            rng.shuffle(options)
            selected = next((pair for pair in options if pair[0] not in used), None)
            if selected is None:
                if rejected is not None:
                    rejected.append(dict(character=character, meaning=meaning, pos=pos,
                                         error=f"Root {code.upper()} ({pos}) exhausted its {len(options)} spellings"))
                    continue
                raise ValueError(
                    f"Root {code.upper()} ({pos}) has exhausted its "
                    f"{len(options)} spellings; revise the lexicon or language rules"
                )
            orth, ipa = selected
            used.add(orth)
            result.append({"orthography": orth, "ipa": ipa, "meaning": meaning,
                           "source": f"{character} ({code.upper()})"})
        except (KeyError, AttributeError, ValueError) as exc:
            raise ValueError(f"Input row {line}: {exc}") from exc
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", help="CSV in manual mode; output in --auto mode")
    parser.add_argument("output", type=Path, nargs="?", help="Generated dictionary CSV (manual mode)")
    parser.add_argument("--auto", action="store_true", help="Fetch codes, English meanings and POS automatically")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--characters", help="Look up specific characters instead of discovering the full inventory")
    group.add_argument("--characters-file", type=Path, help="UTF-8 plain text containing characters to look up")
    group.add_argument("--full", action="store_true", help="Discover all Chinese characters and use bulk dictionaries (implies --auto)")
    senses = parser.add_mutually_exclusive_group()
    senses.add_argument("--all-senses", action="store_true", help="Import all usable senses (default for full discovery)")
    senses.add_argument("--first-sense", action="store_true", help="Import only the first usable sense per character")
    parser.add_argument("--cache", type=Path, default=Path(".lookup_cache"))
    parser.add_argument("--refresh", action="store_true", help="Download again instead of using cached pages")
    parser.add_argument("--seed", type=int, default=0, help="Reproducible random seed (default: 0)")
    args = parser.parse_args()
    args.auto = args.auto or args.full
    full = args.auto and args.characters is None and args.characters_file is None
    all_senses = args.all_senses or (full and not args.first_sense)
    if args.auto:
        if args.output is not None:
            parser.error("--auto takes only one output path")
        output = args.input or Path("dictionary.csv")
    else:
        if args.input is None or args.output is None:
            parser.error("manual mode requires input and output paths; use --auto for automatic lookup")
        if args.input.resolve() == args.output.resolve():
            parser.error("input and output must be different files")
        if args.characters is not None or args.characters_file or args.all_senses or args.first_sense or args.refresh:
            parser.error("lookup options require --auto")
        output = args.output
    try:
        if args.auto:
            from fetch_lexicon import fetch_rows
            characters = (args.characters_file.read_text(encoding="utf-8-sig")
                          if args.characters_file else args.characters)
            if not full and not characters.strip():
                raise ValueError("Character list is empty")
            sidecars = [output.with_suffix(".lexicon.csv"), output.with_suffix(".sources.json")]
            paths = [output.resolve()] + [p.resolve() for p in sidecars]
            if len(set(paths)) != 3 or (args.characters_file and args.characters_file.resolve() in paths):
                raise ValueError("Output and sidecar paths must be distinct from the character input file")
            if full:
                from bulk_lexicon import fetch_full_rows
                rows, audit = fetch_full_rows(args.cache, all_senses, args.refresh)
            else:
                rows, audit = fetch_rows(characters, args.cache, all_senses, args.refresh)
            audit["sense_policy"] = "all usable senses" if all_senses else "first usable sense per character"
            sidecars[1].write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            if not full:
                for failure in audit["failures"]:
                    print(f"Skipped U+{ord(failure['character']):04X}: {failure['error']}")
            if not rows:
                raise ValueError("No usable entries fetched; see the .sources.json report")
            with sidecars[0].open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["character", "meaning", "pos", "codes"])
                writer.writeheader()
                writer.writerows(rows)
            rejected = [] if full else None
            dictionary = generate(rows, args.seed, rejected=rejected)
            audit["generation_failures"] = rejected or []
            audit["pos_summary"] = dict(Counter(entry["detailed_pos"] for entry in audit["entries"]))
            audit["pos_review_entries"] = sum(entry["pos_review_required"] for entry in audit["entries"])
            audit["pos_unresolved_entries"] = sum(entry["detailed_pos"] == "unknown" for entry in audit["entries"])
            audit["generated_entries"] = len(dictionary)
            audit["generated_characters"] = len({row['source'].split(' ')[0] for row in dictionary})
            audit["complete"] = not audit["failures"] and not rejected
            sidecars[1].write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Saved fetched inputs and attribution to {sidecars[0]} and {sidecars[1]}")
            if audit["failures"] or rejected:
                print(f"PARTIAL RESULT: {len(audit['failures']):,} character(s) lack codes/meanings; "
                      f"{len(rejected or []):,} sense(s) exceeded root capacity. See source report.")
        else:
            with args.input.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                required = {"character", "meaning", "pos", "codes"}
                if not required.issubset(reader.fieldnames or []):
                    raise ValueError("Input CSV needs headers: character,meaning,pos,codes")
                dictionary = generate(reader, args.seed)
        # Validate all entries before opening the output.
        with output.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["orthography", "ipa", "meaning", "source"])
            writer.writeheader()
            writer.writerows(dictionary)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    print(f"Wrote {len(dictionary)} entries to {output}")


if __name__ == "__main__":
    main()
