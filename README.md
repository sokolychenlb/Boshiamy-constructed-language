# Boshiamy constructed-language dictionary

Run with Python 3.10 or newer; no packages are required:

```powershell
python generate_dictionary.py --full full_dictionary.csv --seed 42
```

`--full` discovers Han characters in Then.TW's Taiwan traditional (`tc`) and
rare-character (`ext`) code tables. Simplified (`sc`), traditional-to-simplified
(`ct`), Japanese mode and non-Han symbols are excluded. Hashed script filenames are
discovered from the live website, not hardcoded; JavaScript is parsed as data,
never executed. Codes from the two tables are combined, with ties following
table order (`tc`, `ext`) and then the original property order.

Simplified-only characters with traditional counterparts are additionally removed
using CC-CEDICT traditional/simplified pairs and Unihan `kTraditionalVariant`.
Characters independently used in traditional Chinese (e.g. 后 in 皇后 and 干 in
干涉) are preserved when they occur in CC-CEDICT's traditional headwords. Meanings
from CC-CEDICT use only its traditional column. This is a traditional-script
filter, not a restriction to Taiwan's official common-character list; rare and
historical traditional forms remain eligible. Excluded forms and their
traditional counterparts are recorded in `excluded_simplified_characters` in
the source report. This policy applies to full discovery; manual input and
explicit selected-character lookups remain user-controlled.

Full mode downloads CC-CEDICT and Unihan once and joins their single-character
English definitions locally, avoiding tens of thousands of lookup requests.
CC-CEDICT definitions take priority; Unicode Unihan `kDefinition` is the fallback.
All usable senses are imported by default. `--first-sense` selects just the first
usable sense per character. `--auto` without a character list is also full mode.
No character list or input CSV is required.

Characters without meanings or eligible codes are recorded in the source report.
Full mode also records senses that exceed a root's spelling capacity and
continues generating the rest. Thus **full discovery does not guarantee a word
for every character**: the available meanings and finite vowel patterns impose
limits. The report's `complete` flag is false whenever entries are omitted.
There is no fallback to longer codes and no placeholder meaning.

For a specific list, the previous per-character Kaikki/Wiktionary lookup remains:

```powershell
python generate_dictionary.py --auto selected.csv --characters "蝦米人山水火木日月"
```

Or use `--characters-file characters.txt` with UTF-8 plain text (whitespace is
ignored). Selected-character mode defaults to the first usable sense;
`--all-senses` imports all senses. Repeated characters are looked up once.

Requests are sequential, spaced by at least one second, cached in `.lookup_cache`,
and retried up to three times for temporary failures. `--refresh` refreshes cached
pages and bulk data. Rerun the same command after an interruption to reuse complete
cached downloads; interrupted downloads restart. Missing entries are reported as skips; any successful entries produce an
explicitly labelled partial result. If none succeed, the command fails.

Automatic mode also saves `dictionary.lexicon.csv` (reusable fetched inputs) and
`dictionary.sources.json` (source links, POS decisions, failures and attribution).
The dictionary itself still has exactly the four requested columns.

Source order does not guarantee the most frequent sense comes first.
Selected-character and manual modes stop on spelling exhaustion; full mode
records the omitted sense and continues. The fetched inputs remain available for editing.
Definitions can include regional or historical senses and classifier notes.

The shared classifier in `pos_classifier.py` works per sense, so different senses
of a character can receive different first vowels. It uses sense-level POS
labels before entry-level labels, dictionary grammatical categories, explicit
particle/classifier annotations, English function words, adjective glosses, and
English infinitive/copular adjective patterns (e.g. `to eat` versus `to be happy`).
It also consults [Princeton WordNet](https://wordnet.princeton.edu/) lemma indexes
and tagged-sense frequencies. WordNet is downloaded once (about 11 MB) and cached;
no Python packages are needed. Its license is saved as
`.lookup_cache/WORDNET_LICENSE.txt` and linked in the source report.

Nouns and proper names receive `i`, verbs receive `a`, and adjectives, pronouns,
particles, adverbs, conjunctions, classifiers, and other categories receive `u`.
Unresolved or conflicting glosses now receive `other` (`u`) and a low-confidence
review flag, rather than automatically becoming nouns. Bare English lemmas with
only noun/verb ambiguity are provisionally nominal, since dictionary verb glosses
usually use `to`; these receive low confidence and a review flag. Adjective-plus-
noun phrases are recognized separately. Explicit dictionary labels take precedence
over these heuristics. English lexical categories are supporting evidence, not a
guarantee of the Chinese sense's grammar.

Each source-report entry includes `detailed_pos`, `pos_confidence`,
`pos_review_required`, and `pos_basis`, alongside the coarse vowel category `pos`.
The report also includes POS totals and unresolved/review counts. Bulk CC-CEDICT
and Unihan have no POS fields, so their decisions remain inferred and need review;
manual mode always respects the `pos` values you supply. Edit the fetched lexicon
and rerun manual mode to correct an assignment. Semicolon-separated Unihan glosses
are treated as separate senses when importing all senses.

Full-mode definitions come from [CC-CEDICT / MDBG](https://www.mdbg.net/chinese/dictionary?page=cc-cedict)
under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), with
[Unicode Unihan](https://www.unicode.org/reports/tr38/)
under the [Unicode license](https://www.unicode.org/license.txt).
Source URLs and applicable license links are saved in the report.

Selected-mode definitions are adapted from [English Wiktionary](https://en.wiktionary.org/)
via [Kaikki.org / Wiktextract](https://kaikki.org/dictionary/Chinese/).
Retain the generated attribution and source links and follow the applicable
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) terms when
redistributing those definitions. Boshiamy codes come from
[Then.TW](https://boshiamy.then.tw/). HTML layouts may change; unexpected lookup
formats produce an error rather than substituting example codes.

Manual mode remains available:

```powershell
python generate_dictionary.py lexicon.csv dictionary.csv --seed 42
```

The output has exactly four columns: `orthography`, `ipa`, `meaning`, `source`.
The source contains the Chinese character and selected code, e.g. `蝦 (CFA)`.

Add entries to `lexicon.csv` using these columns:

- `character`: one Chinese character per root.
- `meaning`: the intended meaning, supplied by you.
- `pos`: `noun`, `verb`, or `other` (first vowel i, a, or u).
- `codes`: the character's codes, separated by spaces or semicolons. Quote a CSV field if it contains commas.

The included manual examples use the site's displayed codes for 蝦 and 米.
In manual mode, supply all known eligible codes if you want the shortest code
across that complete set. Selected-character mode uses all eligible codes displayed
on the character's lookup page, in display order. Full mode uses the table union
described above.

The shortest supplied code of 2–4 letters wins; equal-length ties preserve input
order. One-letter shortcuts are ignored. Digits and nonletter codes are rejected;
selection numbers must not be included in codes.

Each code letter becomes one consonant using the requested mapping. Every
consonant receives a vowel except optionally the final consonant, giving only
CV syllables and an optional final CVC. Remaining vowels and the final-syllable
form are chosen randomly, subject to spelling uniqueness. A fixed seed and fixed
input order reproduce the output. Reordering or extending the input can change
assignments; this is a batch generator, not a persistent vocabulary registry.

For CFA as a noun, `šifaǧ` / `ʃifaɣ` is one possible result; other seeds may
choose another valid form. IPA is broad and has no added stress marks or slashes.

Uniqueness is global, even when meanings match. Exact duplicate input entries
are skipped. There are 4, 12, or 36 forms per part of speech for roots of 2, 3,
or 4 consonants respectively. If all are used, manual/selected mode fails before
writing the output; full mode logs the omitted entry. It never lengthens a root
or violates the syllable rules.
