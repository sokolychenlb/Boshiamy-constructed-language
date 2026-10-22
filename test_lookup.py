import unittest
import gzip
import io
import zipfile

from bulk_lexicon import discover, parse_table, read_cedict, read_unihan, taiwan_filter

from fetch_lexicon import classify, parse_codes, parse_entries
from pos_classifier import classify_detail
from pos_classifier import WordNetIndex
import pos_classifier
from generate_dictionary import generate, shortest_code


class LookupTests(unittest.TestCase):
    def test_codes_exclude_help_examples_and_selection_numbers(self):
        html = '<div class="text-6xl">蝦</div>'
        html += ''.join(f'<span class="font-mono tracking-widest">{c}</span>'
                        for c in ('CFA', 'COFU', 'COX', 'CFA', 'A', 'CFA1'))
        html += '<code>ZZ</code>'
        self.assertEqual(parse_codes(html, '蝦'), 'CFA COFU COX A')
        self.assertEqual(shortest_code(parse_codes(html, '蝦')), 'a')
        with self.assertRaises(ValueError):
            parse_codes(html, '米')

    def test_entries_filter_language_and_diagnostics(self):
        html = '''<pre>{"word":"蝦","lang_code":"zh","pos":"character",
        "senses":[{"glosses":["shrimp &amp; prawn"]}]}
        {"word":"蝦","lang_code":"ja","pos":"noun"}</pre>
        <pre>{"msg":"diagnostic"}</pre>'''
        entries = parse_entries(html, '蝦')
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['senses'][0]['glosses'], ['shrimp & prawn'])

    def test_pos_is_explicit_about_heuristics(self):
        self.assertEqual(classify({'pos': 'adj'}, {}, 'red')[0], 'other')
        self.assertEqual(classify({'pos': 'verb'}, {}, 'eat')[0], 'verb')
        self.assertEqual(classify({'pos': 'character'}, {}, 'to bend')[0], 'verb')
        self.assertTrue(classify_detail({'pos': 'character'}, {}, 'an obscure undocumented gloss')['pos_review_required'])

    def test_non_nouns_and_sense_specific_labels(self):
        examples = [('big; large; great', 'adjective'), ('good', 'adjective'),
                    ('red', 'adjective'), ('to be happy', 'adjective'),
                    ('I; me; my', 'pronoun'), ('you (informal)', 'pronoun'),
                    ('(pronoun) this; these', 'pronoun'),
                    ('(sentence-final particle) used in questions', 'particle'),
                    ("of; ~'s (possessive particle)", 'particle'),
                    ('classifier for rinses of clothes', 'classifier'),
                    ('very; quite', 'adverb'), ('(joining two nouns) and; together with; with', 'unknown')]
        for gloss, detail in examples:
            with self.subTest(gloss=gloss):
                result = classify_detail({}, {}, gloss)
                self.assertEqual(result['detailed_pos'], detail)
                self.assertEqual(result['pos'], 'other')
        self.assertEqual(classify_detail({'pos': 'noun'}, {'pos': 'adj'}, 'good')['pos'], 'other')
        self.assertEqual(classify_detail({'pos': 'noun'}, {}, 'red')['pos'], 'noun')
        self.assertEqual(classify_detail({}, {}, 'to eat')['pos'], 'verb')
        self.assertEqual(classify_detail({}, {}, 'surname Wang')['pos'], 'noun')

    def test_first_vowels_follow_classification(self):
        for gloss, expected in [('big', 'u'), ('I; me; my', 'u'),
                                ('(question particle)', 'u'), ('to eat', 'a'), ('surname Wang', 'i')]:
            pos = classify_detail({}, {}, gloss)['pos']
            result = generate([dict(character='米', meaning=gloss, pos=pos, codes='MN')])[0]
            self.assertEqual(next(c for c in result['orthography'] if c in 'aiu'), expected)

    def test_wordnet_nominal_phrases_and_ambiguity(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('wordnet/LICENSE', 'Test fixture')
            archive.writestr('wordnet/index.noun', 'rice n 1\nshrimp n 3\nlight n 2\n')
            archive.writestr('wordnet/index.verb', 'rice v 1\nshrimp v 1\nlight v 2\n')
            archive.writestr('wordnet/index.adj', 'uncooked a 1\nlight a 2\n')
            archive.writestr('wordnet/index.adv', '')
            archive.writestr('wordnet/index.sense', 'rice%1:00:00:: 00000000 1 9\nrice%2:00:00:: 00000001 1 0\n')
        previous = pos_classifier.WORDNET
        try:
            pos_classifier.WORDNET = WordNetIndex(buffer.getvalue())
            self.assertEqual(classify_detail({}, {}, 'uncooked rice')['pos'], 'noun')
            shrimp = classify_detail({}, {}, 'shrimp')
            self.assertEqual(shrimp['pos'], 'noun')
            self.assertTrue(shrimp['pos_review_required'])
            # A lemma with adjective/noun/verb ambiguity is not called a noun.
            self.assertEqual(classify_detail({}, {}, 'light')['pos'], 'other')
            self.assertEqual(classify_detail({}, {}, 'mysterious-unlisted-gloss')['detailed_pos'], 'unknown')
        finally:
            pos_classifier.WORDNET = previous

    def test_four_consonant_root_extends_only_after_all_regular_forms(self):
        rows = [dict(character='米', meaning=str(i), pos='noun', codes='ABCD') for i in range(36)]
        result = generate(rows)
        self.assertEqual(len({r['orthography'] for r in result}), 36)
        rows.append(dict(character='米', meaning='overflow', pos='noun', codes='ABCD'))
        rejected = []
        extensions = []
        extended_result = generate(rows, rejected=rejected, extensions=extensions)
        self.assertEqual(extended_result[:36], result)
        self.assertEqual(len(extended_result), 37)
        self.assertEqual(len({r['orthography'] for r in extended_result}), 37)
        self.assertEqual(rejected, [])
        self.assertEqual(len(extensions), 1)
        self.assertEqual(extensions[0]['meaning'], 'overflow')
        self.assertEqual(len(extensions[0]['extended_code']), 5)
        self.assertTrue(all('[added:' not in r['source'] for r in extended_result[:36]))

    def test_two_and_three_consonant_roots_keep_regular_forms(self):
        for code, capacity in [('BC', 4), ('BCD', 12)]:
            with self.subTest(code=code):
                rows = [dict(character='米', meaning=str(i), pos='verb', codes=code) for i in range(capacity + 3)]
                regular = generate(rows[:capacity], seed=3)
                extensions = []
                result = generate(rows, seed=3, extensions=extensions)
                self.assertEqual(result[:capacity], regular)
                self.assertEqual(len(result), capacity + 3)
                self.assertEqual(len({r['orthography'] for r in result}), len(result))
                self.assertEqual(len(extensions), 3)
                self.assertTrue(all(e['extended_code'].startswith(code) and len(e['extended_code']) == len(code) + 1 for e in extensions))

    def test_bulk_tables_are_parsed_as_data(self):
        table = 'const X={蝦:{CFA:3,COFU:0,C:1,CFA1:4},"𠀀":{ABCD:8},"，":{ZZ:2}};export{X as default};'
        self.assertEqual(parse_table(table), {'蝦': ['CFA', 'COFU', 'C'], '𠀀': ['ABCD']})
        with self.assertRaises(ValueError):
            parse_table('throw new Error("never execute downloaded code")')

    def test_bulk_definitions_ignore_compounds_and_redirects(self):
        text = '# comment\n蝦 虾 [xia1] /shrimp/prawn/CL:隻|只[zhi1]/\n蝦米 虾米 [xia1 mi3] /dried shrimp/\n'
        result = read_cedict(gzip.compress(text.encode()))
        self.assertEqual(result, {'蝦': ['shrimp', 'prawn']})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('Unihan_Readings.txt', '# comment\nU+8766\tkDefinition\tshrimp\nU+8766\tkMandarin\txia1\n')
        self.assertEqual(read_unihan(buffer.getvalue()), {'蝦': 'shrimp'})

    def test_discovery_follows_dynamic_assets_and_merges_modes(self):
        pages = {'https://boshiamy.then.tw/': '<script src="/_nuxt/start.js"></script>',
                 'https://boshiamy.then.tw/_nuxt/start.js': ''.join(
                     f'case"{mode}":import("./{mode}.js");' for mode in ('tc', 'sc', 'ct', 'ext'))}
        for mode in ('tc', 'sc', 'ct', 'ext'):
            pages[f'https://boshiamy.then.tw/_nuxt/{mode}.js'] = 'const X={蝦:{CFA:1}};'
        class FakeFetcher:
            def get(self, url):
                return pages[url]
        inventory, urls = discover(FakeFetcher())
        self.assertEqual(inventory, {'蝦': ['CFA']})
        self.assertEqual(len(urls), 2)
        self.assertTrue(all('/tc.js' in u or '/ext.js' in u for u in urls))

    def test_taiwan_filter_preserves_shared_traditional_characters(self):
        data = gzip.compress(('蝦 虾 [xia1] /shrimp/\n後 后 [hou4] /after/\n'
                              '皇后 皇后 [huang2 hou4] /queen/\n乾 干 [gan1] /dry/\n'
                              '干涉 干涉 [gan1 she4] /interfere/\n').encode())
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('Unihan_Variants.txt', 'U+867E\tkTraditionalVariant\tU+8766\n')
        retained, excluded = taiwan_filter(dict.fromkeys('蝦虾後后乾干山', ['AB']), data, buffer.getvalue())
        self.assertEqual(set(retained), set('蝦後后乾干山'))
        self.assertEqual([row['character'] for row in excluded], ['虾'])

    def test_single_letter_roots_extend_only_on_collision(self):
        from generate_dictionary import candidates
        self.assertEqual(list(candidates('b', 'noun')), [('bi', 'bi')])
        self.assertEqual(shortest_code('BA B BCD'), 'b')
        rows = [dict(character='米', meaning=str(i), pos='noun', codes='B') for i in range(130)]
        # Existing longer roots share the same global spelling namespace.
        rows.insert(0, dict(character='山', meaning='mountain', pos='noun', codes='BA'))
        extensions = []
        result = generate(rows, seed=42, extensions=extensions)
        self.assertEqual(len(result), 131)
        self.assertEqual(len({r['orthography'] for r in result}), 131)
        self.assertEqual(result[1]['orthography'], 'bi')
        self.assertNotIn('[added:', result[1]['source'])
        self.assertEqual(len(extensions), 129)
        self.assertTrue(any(len(e['extended_code']) == 3 for e in extensions))
        self.assertEqual(result, generate(rows, seed=42))
        for row in result:
            self.assertRegex(row['orthography'], r'^(?:[^aiu][aiu])+[^aiu]?$')
            self.assertEqual(next(c for c in row['orthography'] if c in 'aiu'), 'i')


if __name__ == '__main__':
    unittest.main()
