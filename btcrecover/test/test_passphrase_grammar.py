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

import json, os, sys, tempfile, time, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from btcrecover.passphrase_grammar import PassphraseGrammar, GrammarError


def grammar(slots, separators=("",), permute=False, priority=False):
    # Tests default priority off, so the expected orders below stay readable; the
    # PriorityOrder class covers the ordering itself (and the shipped default is on).
    return PassphraseGrammar({"passphrase": {
        "slots": list(slots), "separators": list(separators),
        "permute_order": permute, "priority": priority}})

def words(candidates, cases=("asis",), optional=False):
    return {"type": "words", "candidates": list(candidates), "cases": list(cases), "optional": optional}

def digits(lo, hi, optional=False):
    return {"type": "digits", "length": [lo, hi], "optional": optional}

def digit_list(candidates, optional=False):
    return {"type": "digits", "candidates": list(candidates), "optional": optional}

def pool(candidates, choose, optional=False):
    return {"type": "pool", "candidates": list(candidates), "choose": list(choose), "optional": optional}

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


class Pools(unittest.TestCase):
    """"It was two or three of these five, I forget which."

    A pool contributes as many parts as were taken, so separators go between them and any
    reordering applies across them -- it is not one slot holding a joined string.
    """

    def test_takes_a_subset_in_the_order_given(self):
        g = grammar([pool(["민지", "사랑", "2014"], [2, 2])])
        self.assertEqual(list(g.generate()), ["민지사랑", "민지2014", "사랑2014"])

    def test_a_range_of_sizes(self):
        g = grammar([pool(["a", "b", "c"], [1, 3])])
        self.assertEqual(list(g.generate()), ["a", "b", "c", "ab", "ac", "bc", "abc"])

    def test_separators_go_between_the_chosen_words(self):
        g = grammar([pool(["a", "b"], [2, 2])], ["", "-"])
        self.assertEqual(list(g.generate()), ["ab", "a-b"])

    def test_reordering_applies_across_the_pool(self):
        g = grammar([pool(["a", "b"], [2, 2])], ["-"], permute=True)
        self.assertEqual(sorted(g.generate()), ["a-b", "b-a"])

    def test_counts_match_generation(self):
        shapes = [
            [pool(["a", "b", "c"], [1, 3])],
            [pool(["a", "b"], [1, 2]), digits(1, 1)],
            [pool(["a", "b"], [1, 2], optional=True), digits(1, 1)],
            [pool(["a", "b", "c"], [2, 3]), symbols(["!"], optional=True)],
        ]
        for slots in shapes:
            for separators, permute in ((("",), False), (("", "-"), False), (("-",), True)):
                with self.subTest(slots=len(slots), seps=len(separators), permute=permute):
                    g = grammar(slots, separators, permute)
                    produced = list(g.generate())
                    self.assertEqual(g.count(), len(produced))
                    self.assertEqual(len(produced), len(set(produced)))

    def test_skip_resumes(self):
        g = grammar([pool(["a", "b", "c"], [1, 3]), digits(1, 2)], ["", "-"], permute=True)
        full = list(g.generate())
        for k in (0, 1, 17, len(full) // 2, len(full) - 1, len(full)):
            with self.subTest(skip=k):
                self.assertEqual(list(g.generate(skip=k)), full[k:])

    def test_more_words_asked_for_than_given(self):
        # "at least four of these two" cannot be satisfied and should say so
        with self.assertRaises(GrammarError):
            grammar([pool(["a", "b"], [4, 5])])

    def test_asking_for_more_than_there_are_is_capped(self):
        # "up to five of these three" means up to three
        g = grammar([pool(["a", "b", "c"], [3, 5])])
        self.assertEqual(list(g.generate()), ["abc"])

    def test_rejects_a_bad_range(self):
        for bad in ([0, 2], [3, 1]):
            with self.subTest(bad):
                with self.assertRaises(GrammarError):
                    grammar([pool(["a", "b", "c"], bad)])

    def test_refuses_an_unreasonable_number_of_words(self):
        with self.assertRaises(GrammarError):
            grammar([pool([str(i) for i in range(20)], [1, 2])])

    def test_duplicates_are_dropped(self):
        g = grammar([pool(["a", "a", "b"], [2, 2])])
        self.assertEqual(list(g.generate()), ["ab"])


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


class PriorityOrder(unittest.TestCase):
    """Ordering must change only the order. Anything else and the search stops being
    exhaustive, or `count()` stops describing it."""

    SHAPES = [
        ("plain",             [words(["a", "b"]), digits(4, 4)], [""], False),
        ("separators",        [words(["a"]), digits(4, 4)], ["", "-"], False),
        ("optional",          [words(["a"]), digits(4, 4, optional=True),
                               symbols(["!"], optional=True)], ["", "-"], False),
        ("optional+permuted", [words(["a", "b"]), digits(2, 2, optional=True),
                               symbols(["!"], optional=True)], ["", "-"], True),
        ("length range",      [words(["a"]), digits(2, 4)], ["", "-"], False),
        ("digits alone",      [digits(4, 4)], ["-"], False),
        ("length range spanning the year length",
                              [digits(3, 5, optional=True)], ["-", "_"], False),
    ]

    def _pair(self, shape):
        _, slots, seps, permute = shape
        return (PassphraseGrammar({"passphrase": {"slots": slots, "separators": seps,
                                                  "permute_order": permute, "priority": True}}),
                PassphraseGrammar({"passphrase": {"slots": slots, "separators": seps,
                                                  "permute_order": permute, "priority": False}}))

    def test_same_candidates_in_a_different_order(self):
        for shape in self.SHAPES:
            with self.subTest(shape[0]):
                ordered, plain = self._pair(shape)
                a, b = list(ordered.generate()), list(plain.generate())
                self.assertEqual(sorted(a), sorted(b))
                self.assertEqual(len(a), len(set(a)))

    def test_count_is_unaffected(self):
        for shape in self.SHAPES:
            with self.subTest(shape[0]):
                ordered, plain = self._pair(shape)
                self.assertEqual(ordered.count(), plain.count())
                self.assertEqual(ordered.count(), len(list(ordered.generate())))

    def test_skip_resumes_correctly_when_ordered(self):
        for shape in self.SHAPES[:4]:
            with self.subTest(shape[0]):
                ordered, _ = self._pair(shape)
                full = list(ordered.generate())
                for k in (0, 1, 7, len(full) // 2, len(full) - 1, len(full), len(full) + 50):
                    self.assertEqual(list(ordered.generate(skip=k)), full[k:])

    def test_years_are_tried_first(self):
        g = PassphraseGrammar({"passphrase": {"slots": [digits(4, 4)], "priority": True}})
        first = list(g.generate(limit=3))
        self.assertEqual(first, ["1900", "1901", "1902"])

    def test_non_year_digits_are_still_all_reached(self):
        g = PassphraseGrammar({"passphrase": {"slots": [digits(4, 4)], "priority": True}})
        self.assertEqual(sorted(g.generate()), ["{:04d}".format(i) for i in range(10000)])

    def test_a_second_choice_in_one_slot_beats_second_choices_in_two(self):
        """Two slots of the same shape, so each has the same tier ordering.

        Asserted as a property rather than against tier sizes: whatever the model decides a
        digit run is likely to be, a candidate settling for a lower tier in one slot has to
        come before one settling in both. Pinning the boundaries to counts would mean
        rewriting this test every time the model learns something.
        """
        g = PassphraseGrammar({"passphrase": {
            "slots": [digits(4, 4), digits(4, 4)], "separators": ["-"], "priority": True}})
        tiers = g.slots[0].priority_tiers()
        self.assertGreater(len(tiers), 1, "this test needs a slot with more than one tier")

        def tier_of(value):
            index = int(value)
            for t, ranges in enumerate(tiers):
                if any(start <= index < stop for start, stop in ranges):
                    return t
            self.fail("value {} is in no tier".format(value))

        worst_so_far = -1
        for position, candidate in enumerate(g.generate(limit=200000)):
            left, right = candidate.split("-")
            cost = tier_of(left) + tier_of(right)
            self.assertGreaterEqual(cost, worst_so_far,
                                    "cost went down again at position {}".format(position))
            worst_so_far = max(worst_so_far, cost)
        self.assertGreater(worst_so_far, 0, "never reached a lower tier")

    def test_priority_is_on_by_default(self):
        g = PassphraseGrammar({"passphrase": {"slots": [digits(4, 4)]}})
        self.assertTrue(g.priority)
        self.assertEqual(next(g.generate()), "1900")

    def _assert_skip_is_instant(self, grammar, skip):
        """The point is that nothing walks: a walk over a hundred million candidates would
        not return, so the assertion is that it does, and lands somewhere real."""
        started = time.monotonic()
        candidate = next(grammar.generate(skip=skip))
        self.assertLess(time.monotonic() - started, 5.0, "skipping walked instead of dividing")
        return candidate

    def test_skipping_deep_into_an_ordered_space_is_not_a_walk(self):
        # 222 million candidates; if this were walking the test would not finish
        g = PassphraseGrammar({"passphrase": {
            "slots": [words(["a", "b"]), digits(1, 8)], "priority": True}})
        self.assertEqual(g.count(), 222222220)
        deep = self._assert_skip_is_instant(g, 200000000)
        # whatever the model orders first, position 200,000,000 is a real candidate of this
        # grammar, and the one before it is different
        self.assertRegex(deep, r"^[ab]\d+$")
        self.assertNotEqual(deep, self._assert_skip_is_instant(g, 199999999))

    def test_skipping_deep_with_an_optional_slot_is_not_a_walk(self):
        """Emptiness is fixed within a tier, so this divides its way in as well."""
        g = PassphraseGrammar({"passphrase": {
            "slots": [words(["a"]), digits(1, 8, optional=True)],
            "separators": ["-"], "priority": True}})
        self.assertEqual(g.count(), 111111111)      # 111,111,110 digit strings, plus "a" alone
        deep = self._assert_skip_is_instant(g, 100000000)
        self.assertRegex(deep, r"^a(-\d+)?$")


if __name__ == '__main__':
    unittest.main()
