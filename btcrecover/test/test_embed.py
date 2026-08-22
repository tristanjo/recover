#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_embed.py -- unit tests for running a search from inside an application
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

"""A GUI cannot survive the things a terminal shrugs off: a sys.exit on bad input, a
stop button that does not stop anything, a success that arrives with no way to tell NFC
from NFD. These tests cover those, using the same wallet as test_cjk_passphrase -- one
whose passphrase was stored unnormalized, so the whole path has to work to find it.
"""

import json, os, sys, tempfile, threading, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from btcrecover import embed
from btcrecover.passphrase_grammar import GrammarError


MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
ADDR_NFC = "12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu"   # wallet that stored the passphrase as NFC
PASSPHRASE = "비밀번호2024"


def config(slots=None, **wallet_overrides):
    wallet = {"type": "bip39", "addresses": [ADDR_NFC], "language": "en",
              "derivation_paths": ["m/44'/0'/0'/0"], "address_limit": 5}
    wallet.update(wallet_overrides)
    return {
        "version": 1,
        "wallet": wallet,
        "passphrase": {
            "slots": slots if slots is not None else [
                {"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
                {"type": "digits", "candidates": ["2023", "2024", "2025"]},
            ],
            "separators": [""],
            "normalizations": ["NFKD", "NFC"],
        },
    }


class Planning(unittest.TestCase):

    def test_reads_the_wallet_section(self):
        plan = embed.SearchPlan(config())
        self.assertEqual(plan.addresses, [ADDR_NFC])
        self.assertEqual(plan.derivation_paths, ["m/44'/0'/0'/0"])
        self.assertEqual(plan.address_limit, 5)
        self.assertEqual(plan.normalizations, ["NFKD", "NFC"])
        self.assertEqual(plan.candidate_count(), 3)

    def test_a_single_path_may_be_a_bare_string(self):
        plan = embed.SearchPlan(config(derivation_paths="m/84'/0'/0'/0"))
        self.assertEqual(plan.derivation_paths, ["m/84'/0'/0'/0"])

    def test_missing_paths_fall_back_to_the_common_three(self):
        cfg = config()
        del cfg["wallet"]["derivation_paths"]
        self.assertEqual(embed.SearchPlan(cfg).derivation_paths, embed.DEFAULT_PATHS)

    def test_an_address_is_required(self):
        # without one there is nothing to recognise a correct passphrase by
        with self.assertRaises(GrammarError):
            embed.SearchPlan(config(addresses=[]))

    def test_the_config_never_carries_a_mnemonic(self):
        plan = embed.SearchPlan(config())
        self.assertNotIn("--mnemonic", json.dumps(config()))
        self.assertIn("--mnemonic", plan._argv("some words"))

    def test_from_file_reports_bad_json_clearly(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = f.name
        try:
            with self.assertRaises(GrammarError):
                embed.SearchPlan.from_file(path)
        finally:
            os.unlink(path)


class Searching(unittest.TestCase):

    def test_finds_the_passphrase_and_names_the_form(self):
        plan = embed.SearchPlan(config())
        result = embed.run(plan, MNEMONIC)
        self.assertTrue(result.found, result.error or result.log)
        self.assertEqual(result.passphrase, PASSPHRASE)
        # NFC and NFD are the same glyphs; without the label the user cannot re-enter it
        self.assertEqual(result.normalization, "NFC")

    def test_reports_progress_on_success(self):
        # a short search finds the answer in the first chunk, so the only report is the
        # final one -- which still has to arrive, or a progress bar freezes mid-way
        plan = embed.SearchPlan(config())
        seen = []
        result = embed.run(plan, MNEMONIC, progress=lambda tried, total: seen.append((tried, total)))
        self.assertTrue(result.found)
        self.assertTrue(seen)
        self.assertEqual(seen[-1][1], plan.candidate_count())

    def test_reports_progress_as_it_goes(self):
        plan = embed.SearchPlan(config(slots=[
            {"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
            {"type": "digits", "length": [4, 4]},
        ], addresses=["1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]))   # no match, so it runs to the end
        seen = []
        embed.run(plan, MNEMONIC, progress=lambda tried, total: seen.append((tried, total)))
        self.assertGreater(len(seen), 1)
        self.assertTrue(all(total == plan.candidate_count() for _, total in seen))
        self.assertEqual(sorted(t for t, _ in seen), [t for t, _ in seen])   # monotonic

    def test_a_miss_is_a_result_not_an_error(self):
        plan = embed.SearchPlan(config(slots=[
            {"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
            {"type": "digits", "candidates": ["0001", "0002"]},
        ]))
        result = embed.run(plan, MNEMONIC)
        self.assertFalse(result.found)
        self.assertIsNone(result.error)
        self.assertFalse(result.aborted)

    def test_abort_stops_the_search(self):
        plan = embed.SearchPlan(config(slots=[
            {"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
            {"type": "digits", "length": [4, 4]},
        ]))
        stop = threading.Event()
        result = embed.run(plan, MNEMONIC, progress=lambda *_: stop.set(), abort=stop)
        self.assertTrue(result.aborted)
        self.assertFalse(result.found)
        self.assertLess(result.tried, plan.candidate_count())

    def test_skip_resumes_past_the_answer(self):
        plan = embed.SearchPlan(config())
        self.assertTrue(embed.run(plan, MNEMONIC).found)
        # the answer is the second of three candidates, so skipping two steps over it
        self.assertFalse(embed.run(plan, MNEMONIC, skip=2).found)

    def test_skipping_everything_is_an_error_not_a_silent_miss(self):
        plan = embed.SearchPlan(config())
        result = embed.run(plan, MNEMONIC, skip=plan.candidate_count())
        self.assertIsNotNone(result.error)


class Typos(unittest.TestCase):
    """Mistyping is btcrecover's job; embed only has to ask for it correctly."""

    def test_nothing_asked_for_means_no_arguments(self):
        # --typos on its own is an error, so an empty answer must produce an empty list
        self.assertEqual(embed._typo_flags({}), [])
        self.assertEqual(embed._typo_flags({"max": 2}), [])
        self.assertEqual(embed._typo_flags({"max": 0, "case": True}), [])

    def test_translates_each_kind(self):
        self.assertEqual(embed._typo_flags({"case": True, "swap": True}),
                         ["--typos", "1", "--typos-case", "--typos-swap"])
        self.assertEqual(embed._typo_flags({"max": 3, "delete": True}),
                         ["--typos", "3", "--typos-delete"])

    def test_the_keyboard_map_is_found_from_the_package(self):
        # not from the working directory: a frozen build starts wherever the user is
        flags = embed._typo_flags({"keyboard": True})
        self.assertEqual(flags[-2], "--typos-map")
        self.assertTrue(os.path.isabs(flags[-1]))
        self.assertTrue(os.path.exists(flags[-1]), flags[-1])

    def test_the_shifted_map_is_the_one_used(self):
        """us-map.txt covers unshifted keys only and does nothing to a passphrase with a
        capital in it -- seven variants of "TREZOr" against thirty-four."""
        self.assertIn("us-with-shifts-map", embed._typo_flags({"keyboard": True})[-1])

    def test_a_mistyped_passphrase_is_recovered(self):
        """Each kind is paired with a mistyping it can actually undo.

        The real passphrase ends 2024. Transposing its last two digits gives 2042, which
        only --typos-swap reaches; typing an extra 4 gives 20244, which only --typos-delete
        removes. Pairing a kind with a mistyping it cannot fix tests nothing.
        """
        for mistyped, kind in (("2042", "swap"), ("20244", "delete")):
            with self.subTest(mistyped=mistyped, kind=kind):
                cfg = config(slots=[{"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
                                    {"type": "digits", "candidates": [mistyped]}])
                self.assertFalse(embed.run(embed.SearchPlan(cfg), MNEMONIC).found,
                                 "should not be found without the typo option")
                cfg["typos"] = {"max": 1, kind: True}
                result = embed.run(embed.SearchPlan(cfg), MNEMONIC)
                self.assertTrue(result.found, result.error or result.log[-400:])
                self.assertEqual(result.passphrase, PASSPHRASE)

    def test_typo_flags_reach_the_command_line(self):
        cfg = config()
        cfg["typos"] = {"max": 2, "case": True}
        argv = embed.SearchPlan(cfg)._argv("some words")
        self.assertIn("--typos", argv)
        self.assertEqual(argv[argv.index("--typos") + 1], "2")
        self.assertIn("--typos-case", argv)


class Failures(unittest.TestCase):
    """btcrpass reports bad input by calling sys.exit; a GUI must get a message instead."""

    def test_empty_mnemonic(self):
        result = embed.run(embed.SearchPlan(config()), "   ")
        self.assertIn("mnemonic", result.error)

    def test_invalid_mnemonic_does_not_exit_the_process(self):
        result = embed.run(embed.SearchPlan(config()), "not actually a seed phrase at all")
        self.assertIsNotNone(result.error)
        self.assertFalse(result.found)

    def test_ambiguous_wordlist_language_is_reported(self):
        cfg = config()
        del cfg["wallet"]["language"]     # this mnemonic scores almost equally as en and fr
        result = embed.run(embed.SearchPlan(cfg), MNEMONIC)
        self.assertIsNotNone(result.error)
        self.assertIn("language", result.error.lower())


class FrozenStart(unittest.TestCase):

    def test_missing_console_streams_are_replaced(self):
        # a windowed PyInstaller build leaves these None, and BTCRecover prints from its
        # workers exactly when a match is found
        saved_out, saved_err = sys.stdout, sys.stderr
        try:
            sys.stdout = sys.stderr = None
            embed._ensure_streams()
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)
            print("this must not raise", file=sys.stdout)
        finally:
            for stream in (sys.stdout, sys.stderr):
                if stream not in (saved_out, saved_err) and stream is not None:
                    stream.close()
            sys.stdout, sys.stderr = saved_out, saved_err

    def test_existing_streams_are_left_alone(self):
        before = sys.stdout
        embed._ensure_streams()
        self.assertIs(sys.stdout, before)

    def test_a_console_that_cannot_encode_hangul_is_repaired(self):
        """A Windows console encodes as cp1252, which has no Hangul at all.

        BTCRecover prints from its workers at the moment a match is found, and a seed
        phrase from the Korean wordlist would raise on its first character -- making
        success the one outcome that crashes.
        """
        import io as _io
        saved = sys.stdout
        buffer = _io.BytesIO()
        try:
            sys.stdout = _io.TextIOWrapper(buffer, encoding="cp1252")
            with self.assertRaises(UnicodeEncodeError):     # the failure being fixed
                print("비밀번호2024")
                sys.stdout.flush()

            sys.stdout = _io.TextIOWrapper(_io.BytesIO(), encoding="cp1252")
            embed._ensure_streams()
            print("비밀번호2024")                            # must not raise
            sys.stdout.flush()
            self.assertEqual(sys.stdout.encoding.lower().replace("-", ""), "utf8")
        finally:
            sys.stdout = saved


if __name__ == '__main__':
    unittest.main()
