#!/usr/bin/env python
# -*- coding: utf-8 -*-

# hangul_keys.py -- what Hangul turns into when the IME was never switched on
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

"""Korean is typed by pressing Latin keys and letting the IME assemble syllables from them.
With the IME off, those same keystrokes arrive as the Latin letters themselves: someone
setting the passphrase 비밀번호 gets qlalfqjsgh stored instead.

A password field shows dots, so nothing about it looks wrong. It keeps working, because the
same wrong keystrokes are typed every time -- right up until someone tries to enter the
passphrase they believe they chose, into a wallet that never saw it.

This converts what they remember into what was actually stored. Standard 두벌식 layout,
which is what an unmodified Korean Windows or macOS types.
"""

__all__ = ["to_keystrokes", "contains_hangul"]

# The three positions a Hangul syllable is built from, in Unicode order, each mapped to the
# keys pressed to produce it. Compound vowels and final clusters take two keystrokes, which
# is why these are strings rather than characters.
INITIALS = ["r", "R", "s", "e", "E", "f", "a", "q", "Q", "t",
            "T", "d", "w", "W", "c", "z", "x", "v", "g"]

MEDIALS = ["k", "o", "i", "O", "j", "p", "u", "P", "h", "hk",
           "ho", "hl", "y", "n", "nj", "np", "nl", "b", "m", "ml", "l"]

FINALS = ["", "r", "R", "rt", "s", "sw", "sg", "e", "f", "fr",
          "fa", "fq", "ft", "fx", "fv", "fg", "a", "q", "qt", "t",
          "T", "d", "w", "c", "z", "x", "v", "g"]

# Jamo typed on their own, without a syllable around them.
STANDALONE = {
    "ㄱ": "r", "ㄲ": "R", "ㄴ": "s", "ㄷ": "e", "ㄸ": "E", "ㄹ": "f", "ㅁ": "a",
    "ㅂ": "q", "ㅃ": "Q", "ㅅ": "t", "ㅆ": "T", "ㅇ": "d", "ㅈ": "w", "ㅉ": "W",
    "ㅊ": "c", "ㅋ": "z", "ㅌ": "x", "ㅍ": "v", "ㅎ": "g",
    "ㅏ": "k", "ㅐ": "o", "ㅑ": "i", "ㅒ": "O", "ㅓ": "j", "ㅔ": "p", "ㅕ": "u",
    "ㅖ": "P", "ㅗ": "h", "ㅘ": "hk", "ㅙ": "ho", "ㅚ": "hl", "ㅛ": "y", "ㅜ": "n",
    "ㅝ": "nj", "ㅞ": "np", "ㅟ": "nl", "ㅠ": "b", "ㅡ": "m", "ㅢ": "ml", "ㅣ": "l",
    "ㄳ": "rt", "ㄵ": "sw", "ㄶ": "sg", "ㄺ": "fr", "ㄻ": "fa", "ㄼ": "fq",
    "ㄽ": "ft", "ㄾ": "fx", "ㄿ": "fv", "ㅀ": "fg", "ㅄ": "qt",
}

SYLLABLE_START = 0xAC00
SYLLABLE_END = 0xD7A3


def contains_hangul(text):
    """Whether converting `text` could produce anything different from `text`."""
    return any(SYLLABLE_START <= ord(c) <= SYLLABLE_END or c in STANDALONE for c in text or "")


def to_keystrokes(text):
    """The Latin characters a 두벌식 keyboard sends while typing `text`.

    Anything that is not Hangul -- digits, symbols, Latin already -- is passed through, since
    those keys are the same either way and an IME does not touch them.

        >>> to_keystrokes("비밀번호2024")
        'qlalfqjsgh2024'
    """
    out = []
    for char in text or "":
        code = ord(char)
        if SYLLABLE_START <= code <= SYLLABLE_END:
            index = code - SYLLABLE_START
            out.append(INITIALS[index // (21 * 28)])
            out.append(MEDIALS[(index // 28) % 21])
            out.append(FINALS[index % 28])
        else:
            out.append(STANDALONE.get(char, char))
    return "".join(out)
