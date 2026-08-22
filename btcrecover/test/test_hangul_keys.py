#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_hangul_keys.py -- unit tests for the IME-off keystroke conversion
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

"""These vectors are the contract. The diagnostic page carries the same tables, generated
from this module, and must produce the same answers -- a page that quotes a customer one
search while the program runs another is worse than no page at all.

The page lives in its own repository now (see docs/Passphrase_Grammar.md); its own tests
check it against this one.
"""

import os, sys, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from btcrecover.hangul_keys import to_keystrokes, contains_hangul
from btcrecover.passphrase_grammar import PassphraseGrammar


# What a 두벌식 keyboard sends for each of these, with the IME switched off.
VECTORS = [
    ("비밀번호",      "qlalfqjsgh"),
    ("안녕",          "dkssud"),
    ("사랑",          "tkfkd"),
    ("한글",          "gksrmf"),
    ("우리집",        "dnflwlq"),
    ("민지",          "alswl"),
    ("비밀번호2024",  "qlalfqjsgh2024"),   # digits are the same keys either way
    ("사랑해!",       "tkfkdgo!"),         # so is punctuation
    ("값",            "rkqt"),             # ㅄ, a two-key final cluster
    ("왜",            "dho"),              # ㅙ, a two-key compound vowel
    ("의사",          "dmltk"),            # ㅢ, and an initial ㅇ that is not silent here
    ("뭐",            "anj"),
    ("닭",            "ekfr"),             # ㄺ
    ("password",      "password"),         # already Latin: unchanged
    ("",              ""),
]


class Conversion(unittest.TestCase):

    def test_vectors(self):
        for hangul, keystrokes in VECTORS:
            with self.subTest(hangul):
                self.assertEqual(to_keystrokes(hangul), keystrokes)

    def test_latin_is_left_alone(self):
        for text in ("minji2014", "TREZOR", "!@#$", "2024"):
            self.assertEqual(to_keystrokes(text), text)

    def test_standalone_jamo(self):
        # a lone consonant or vowel, not part of a syllable
        self.assertEqual(to_keystrokes("ㅁ"), "a")
        self.assertEqual(to_keystrokes("ㅢ"), "ml")

    def test_contains_hangul(self):
        self.assertTrue(contains_hangul("비밀번호"))
        self.assertTrue(contains_hangul("wallet비밀"))
        self.assertTrue(contains_hangul("ㅁ"))
        self.assertFalse(contains_hangul("password2024"))
        self.assertFalse(contains_hangul(""))
        self.assertFalse(contains_hangul(None))


class InTheGrammar(unittest.TestCase):

    @staticmethod
    def _words(candidates, **kwds):
        slot = {"type": "words", "candidates": candidates, "cases": ["asis"]}
        slot.update(kwds)
        return PassphraseGrammar({"passphrase": {"slots": [slot], "separators": [""]}})

    def test_off_by_default(self):
        self.assertEqual(list(self._words(["비밀번호"]).generate()), ["비밀번호"])

    def test_adds_the_keystroke_form_after_the_word(self):
        # the word itself first: someone who remembers Korean most likely did type Korean
        self.assertEqual(list(self._words(["비밀번호", "우리집"], keystrokes=True).generate()),
                         ["비밀번호", "qlalfqjsgh", "우리집", "dnflwlq"])

    def test_costs_nothing_for_a_latin_word(self):
        # the IME-off form of a Latin word is the word, and duplicates are dropped
        grammar = self._words(["minji"], keystrokes=True)
        self.assertEqual(list(grammar.generate()), ["minji"])
        self.assertEqual(grammar.count(), 1)

    def test_combines_with_case_variants(self):
        slot = {"type": "words", "candidates": ["Wallet", "비밀"],
                "cases": ["asis", "upper"], "keystrokes": True}
        grammar = PassphraseGrammar({"passphrase": {"slots": [slot], "separators": [""]}})
        # 비밀 is 비(ql) + 밀(alf), which is the front of 비밀번호 -> qlalfqjsgh
        self.assertEqual(list(grammar.generate()),
                         ["Wallet", "WALLET", "비밀", "qlalf"])

    def test_count_matches_generation(self):
        for candidates in (["비밀번호"], ["비밀번호", "우리집"], ["minji", "비밀"], ["minji"]):
            with self.subTest(candidates):
                grammar = self._words(candidates, keystrokes=True)
                self.assertEqual(grammar.count(), len(list(grammar.generate())))


if __name__ == '__main__':
    unittest.main()
