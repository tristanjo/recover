#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_passphrase_grammar.py -- unit tests for the passphrase grammar expander
# Copyright (C) 2026 tristanjo
#
# This file is part of btcrecover.
#
# btcrecover is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version
# 2 of the License, or (at your option) any later version.
#
# btcrecover is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see http://www.gnu.org/licenses/

"""The grammar is a contract between two implementations: the diagnostic web tool
quotes the customer a candidate count and an ETA, and this expander later produces
the candidates that get searched. If the two disagree, the quote was a lie.

So these tests pin down three things: that count() is exactly what generate() yields,
that the numbers match the ones webapp/diagnostic.html arrives at independently, and
that the order is stable enough for an interrupted search to resume.
"""

import json, os, sys, tempfile, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from btcrecover.passphrase_grammar import PassphraseGrammar, GrammarError


def grammar(slots, separators=("",), permute=False):
    return PassphraseGrammar({"passphrase": {
        "slots": list(slots), "separators": list(separators), "permute_order": permute}})

def words(candidates, cases=("asis",), optional=False):
    return {"type": "words", "candidates": list(candidates), "cases": list(cases), "optional": optional}

def digits(lo, hi, optional=False):
    return {"type": "digits", "length": [lo, hi], "optional": optional}

def digit_list(candidates, optional=False):
    return {"type": "digits", "candidates": list(candidates), "optional": optional}

def symbols(candidates, optional=False):
    return {"type": "symbols", "candidates": list(candidates), "optional": optional}

def fixed(candidates, optional=False):
    return {"type": "fixed", "candidates": list(candidates), "optional": optional}


class CountMatchesGeneration(unittest.TestCase):
    """count() must be exactly what generate() produces -- not an estimate."""

    CASES = [
        ("plain",              grammar([words(["a", "b"]), words(["x", "y"])])),
        ("separators",         grammar([words(["a", "b"]), words(["x", "y"])], ["", "-", "_"])),
        ("permuted",           grammar([words(["a", "b"]), words(["x", "y"])], [""], True)),
        ("permuted+separators", grammar([words(["a", "b"]), words(["x", "y"]), symbols(["!"])], ["", "-"], True)),
        ("optional",           grammar([words(["a", "b"]), words(["x", "y"], optional=True)], ["", "-"])),
        ("optional+permuted",  grammar([words(["a", "b"]), words(["x", "y"], optional=True),
                                        symbols(["!"], optional=True)], ["", "-"], True)),
        ("all optional",       grammar([words(["a"], optional=True), words(["x"], optional=True)], ["", "-"])),
        ("digit range",        grammar([words(["a"]), digits(1, 2)])),
        ("digit range+optional", grammar([words(["a"]), digits(1, 2, optional=True)], ["", "-"])),
        ("case variants",      grammar([words(["password", "Min"], ["asis", "lower", "title", "upper"])])),
        ("single slot ignores separators",
                               grammar([digits(2, 3, optional=True)], ["-", "_"], True)),
    ]

    def test_count_equals_generated(self):
        for name, g in self.CASES:
            with self.subTest(name):
                self.assertEqual(g.count(), len(list(g.generate())))

    def test_no_duplicates(self):
        for name, g in self.CASES:
            with self.subTest(name):
                produced = list(g.generate())
                self.assertEqual(len(produced), len(set(produced)))

    def test_empty_slot_takes_its_separator_with_it(self):
        g = grammar([words(["a"]), words(["b"], optional=True), words(["c"])], ["-"])
        self.assertEqual(list(g.generate()), ["a-b-c", "a-c"])

    def test_one_part_is_emitted_once_per_separator_set(self):
        # a lone part has nowhere to put a separator, so three separators still give one candidate
        g = grammar([words(["solo"])], ["", "-", "_"])
        self.assertEqual(list(g.generate()), ["solo"])


class WebToolAgreement(unittest.TestCase):
    """The same grammars, counted independently by webapp/diagnostic.html.

    These expectations were read off the web tool, not computed here; they are what a
    customer would have been quoted. If this test fails, one of the two implementations
    drifted and the quoted ETA no longer describes the search that will actually run.
    """

    CASES = [
        (13,    grammar([words(["Beta"], ["asis", "title"]), symbols(["!", "@", "#"], optional=True)],
                        [" ", "_"], True)),
        (3,     grammar([fixed(["!", "@", "#"], optional=True)], ["", " "])),
        (6,     grammar([words(["비밀번호"], optional=True), symbols(["!", "@", "#"])], [""])),
        (660,   grammar([digits(1, 2), fixed(["!", "@", "#"])], ["_"], True)),
        (997,   grammar([words(["x", "비밀번호"], ["asis", "lower"], optional=True),
                         digits(1, 2, optional=True), fixed(["btc"])], [" ", "-", "_"])),
        (59400, grammar([digits(2, 3), digit_list(["1988", "2014", "0301"]), symbols(["!", "@", "#"])],
                        [" "], True)),
        (134,   grammar([fixed(["!", "@", "#"], optional=True), words(["alpha"], ["asis", "title"]),
                         fixed(["!", "@", "#"], optional=True)], [""], True)),
        (26408, grammar([digits(2, 3, optional=True), fixed(["!", "@"]), words(["Beta", "alpha"])],
                        ["-"], True)),
        (1100,  grammar([digits(2, 3, optional=True)], ["-", "_"], True)),
    ]

    def test_counts_match_the_web_tool(self):
        for expected, g in self.CASES:
            with self.subTest(expected=expected):
                self.assertEqual(g.count(), expected)


class Resumption(unittest.TestCase):

    def setUp(self):
        self.g = grammar([words(["a", "b"]), words(["x", "y"], optional=True),
                          symbols(["!"], optional=True)], ["", "-"], True)
        self.full = list(self.g.generate())

    def test_skip_resumes_at_the_same_point(self):
        for k in (0, 1, 3, 7, len(self.full) - 1, len(self.full)):
            with self.subTest(skip=k):
                self.assertEqual(list(self.g.generate(skip=k)), self.full[k:])

    def test_skipping_past_the_end_yields_nothing(self):
        self.assertEqual(list(self.g.generate(skip=len(self.full) + 100)), [])

    def test_limit(self):
        self.assertEqual(list(self.g.generate(limit=5)), self.full[:5])
        self.assertEqual(list(self.g.generate(skip=2, limit=3)), self.full[2:5])

    def test_order_is_stable_across_runs(self):
        self.assertEqual(list(self.g.generate()), self.full)

    def test_negative_skip_is_rejected(self):
        with self.assertRaises(ValueError):
            list(self.g.generate(skip=-1))


class LargeSlotsStayLazy(unittest.TestCase):
    """A slot covering every 8-digit number must cost nothing until asked."""

    def test_hundred_million_candidates_are_not_materialized(self):
        g = grammar([digits(1, 8)])
        self.assertEqual(g.count(), 111111110)

    def test_random_access_deep_into_the_space(self):
        g = grammar([digits(1, 8)])
        for skip, expected in [(0, "0"), (9, "9"), (10, "00"), (109, "99"),
                               (110, "000"), (1109, "999"), (111111109, "99999999")]:
            with self.subTest(skip=skip):
                self.assertEqual(next(g.generate(skip=skip)), expected)

    def test_leading_zeros_are_preserved(self):
        # someone who wrote 0301 for a birthday did not write 301
        g = grammar([digits(4, 4)])
        self.assertEqual(next(g.generate(skip=301)), "0301")


class Parsing(unittest.TestCase):

    def test_words_are_expanded_word_major(self):
        # every form of the first word before the second, so the user's own priority order survives
        g = grammar([words(["ab", "cd"], ["asis", "upper"])])
        self.assertEqual(list(g.generate()), ["ab", "AB", "cd", "CD"])

    def test_duplicate_candidates_are_dropped(self):
        g = grammar([words(["a", "a", "b"])])
        self.assertEqual(list(g.generate()), ["a", "b"])

    def test_case_variants_that_collide_are_dropped(self):
        # "min" lowercased is still "min", so asis and lower are one variant
        g = grammar([words(["min"], ["asis", "lower", "upper"])])
        self.assertEqual(list(g.generate()), ["min", "MIN"])

    def test_slots_with_no_candidates_are_ignored(self):
        g = grammar([words([]), words(["a"])])
        self.assertEqual(list(g.generate()), ["a"])

    def test_duplicate_separators_are_deduped(self):
        g = grammar([words(["a"]), words(["b"])], ["-", "-", ""])
        self.assertEqual(list(g.generate()), ["a-b", "ab"])

    def test_accepts_a_full_config_document(self):
        # what the web tool actually writes, wrapper and all
        g = PassphraseGrammar({"version": 1, "wallet": {"type": "bip39"},
                               "passphrase": {"slots": [words(["a"])], "separators": [""],
                                              "normalizations": ["NFKD", "NFC"]}})
        self.assertEqual(list(g.generate()), ["a"])
        self.assertEqual(g.normalizations, ["NFKD", "NFC"])

    def test_from_file(self):
        doc = {"passphrase": {"slots": [words(["a", "b"])], "separators": [""]}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(doc, f)
            path = f.name
        try:
            self.assertEqual(list(PassphraseGrammar.from_file(path).generate()), ["a", "b"])
        finally:
            os.unlink(path)


class Rejections(unittest.TestCase):

    def test_no_slots(self):
        with self.assertRaises(GrammarError):
            grammar([])

    def test_every_slot_empty(self):
        with self.assertRaises(GrammarError):
            grammar([words([]), symbols([])])

    def test_unknown_slot_type(self):
        with self.assertRaises(GrammarError):
            grammar([{"type": "runes", "candidates": ["a"]}])

    def test_unknown_case_transform(self):
        with self.assertRaises(GrammarError):
            grammar([words(["a"], ["sPoNgEbOb"])])

    def test_bad_digit_range(self):
        with self.assertRaises(GrammarError):
            grammar([digits(3, 1)])
        with self.assertRaises(GrammarError):
            grammar([digits(0, 2)])

    def test_malformed_digit_length(self):
        with self.assertRaises(GrammarError):
            grammar([{"type": "digits", "length": [4]}])

    def test_not_an_object(self):
        with self.assertRaises(GrammarError):
            PassphraseGrammar([1, 2, 3])


if __name__ == '__main__':
    unittest.main()
