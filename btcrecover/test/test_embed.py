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

class SplitAcrossMachines(unittest.TestCase):
    """One long search, several computers, each given the same config with a different part.

    The property that matters is that the parts tile the whole exactly. An overlap wastes
    time; a gap is worse, because the run that skipped the answer reports "not found" and
    looks exactly like a search that genuinely came up empty.
    """

    @staticmethod
    def part(index, of, slots=None):
        cfg = config(slots=slots)
        cfg["search"] = {"part": index, "of": of}
        return embed.SearchPlan(cfg)

    def bounds(self, of, slots=None):
        return [self.part(i, of, slots).part_bounds() for i in range(1, of + 1)]

    def test_the_parts_cover_everything_exactly_once(self):
        total = embed.SearchPlan(config()).total_count()
        for of in (1, 2, 3, 7, 100):
            with self.subTest(of=of):
                spans = self.bounds(of)
                self.assertEqual(spans[0][0], 0)
                self.assertEqual(spans[-1][1], total)
                for before, after in zip(spans, spans[1:]):
                    self.assertEqual(before[1], after[0])
                self.assertEqual(sum(b - a for a, b in spans), total)

    def test_more_parts_than_candidates_leaves_no_gap(self):
        # asking for 100 parts of a 3-candidate search gives mostly empty ones, which is
        # silly but must still add up rather than losing a candidate to rounding
        spans = self.bounds(100)
        self.assertEqual(sum(b - a for a, b in spans), embed.SearchPlan(config()).total_count())

    def test_a_part_searches_only_its_own_stretch(self):
        plan = self.part(2, 3)
        start, stop = plan.part_bounds()
        mine = list(plan.grammar.generate(skip=start, limit=stop - start))
        self.assertEqual(len(mine), plan.candidate_count())
        whole = list(plan.grammar.generate())
        self.assertEqual(mine, whole[start:stop])

    def test_exactly_one_part_finds_it(self):
        found = [i for i in range(1, 4)
                 if embed.run(self.part(i, 3), MNEMONIC).found]
        self.assertEqual(len(found), 1, "found in parts {}".format(found))

    def test_a_part_that_misses_is_not_an_error(self):
        misses = [embed.run(self.part(i, 3), MNEMONIC) for i in range(1, 4)]
        for r in misses:
            self.assertIsNone(r.error)

    def test_without_a_search_section_nothing_changes(self):
        plan = embed.SearchPlan(config())
        self.assertEqual(plan.part, 1)
        self.assertEqual(plan.of, 1)
        self.assertEqual(plan.part_bounds(), (0, plan.total_count()))
        self.assertEqual(plan.candidate_count(), plan.total_count())

    def test_a_part_outside_the_range_is_refused(self):
        # a customer copying "part 8 of 7" by hand should be told, not quietly given nothing
        for index, of in ((0, 3), (4, 3), (-1, 3)):
            with self.subTest(part=index, of=of):
                with self.assertRaises(GrammarError):
                    self.part(index, of)



if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from btcrecover import embed
from btcrecover.passphrase_grammar import GrammarError


MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
ADDR_NFC = "12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu"   # wallet that stored the passphrase as NFC
PASSPHRASE = "비밀번호2024"


def config(slots=None, typos=None, **wallet_overrides):
    wallet = {"type": "bip39", "addresses": [ADDR_NFC], "language": "en",
              "derivation_paths": ["m/44'/0'/0'/0"], "address_limit": 5}
    wallet.update(wallet_overrides)
    return {
        "version": 1,
        "wallet": wallet,
        "typos": typos or {},
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

    def test_progress_never_runs_past_the_end(self):
        """The bar read "78256.4%" over "122,080 / 156".

        btcrpass counts passwords tried -- every typo variant of every candidate -- and
        the total here counts candidates. With typos on, one is hundreds of times the
        other, so the two must not be divided by each other. Progress is counted off the
        candidate generator instead, which this side owns and can count exactly.
        """
        plan = embed.SearchPlan(config(
            slots=[{"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
                   {"type": "digits", "length": [1, 3]}],
            typos={"case": True, "swap": True, "max": 1}))
        seen = []
        embed.run(plan, MNEMONIC, progress=lambda tried, total: seen.append((tried, total)))

        self.assertTrue(seen, "no progress at all")
        total = plan.candidate_count()
        for tried, reported in seen:
            self.assertEqual(reported, total)
            self.assertLessEqual(tried, total,
                                 "{:,} of {:,} is {:.0f}%".format(tried, total,
                                                                  100.0 * tried / total))
        self.assertEqual(seen[-1][0], total, "the bar stopped short of the end")

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

    def test_two_maps_are_merged_rather_than_one_overwriting_the_other(self):
        """--typos-map takes a single file and the last one wins, so asking for both a
        neighbouring key and leetspeak would silently drop one."""
        flags = embed._typo_flags({"keyboard": True, "leet": True})
        self.assertEqual(flags.count("--typos-map"), 1)
        merged = flags[flags.index("--typos-map") + 1]
        with open(merged, "r", encoding="utf-8") as f:
            body = f.read()
        for name in ("us-with-shifts-map.txt", "leet-map.txt"):
            self.assertIn(name, body)

    def test_typo_flags_reach_the_command_line(self):
        cfg = config()
        cfg["typos"] = {"max": 2, "case": True}
        argv = embed.SearchPlan(cfg)._argv("some words")
        self.assertIn("--typos", argv)
        self.assertEqual(argv[argv.index("--typos") + 1], "2")
        self.assertIn("--typos-case", argv)


class WorkerFeeding(unittest.TestCase):
    """How much work goes to a worker at a time, which nothing user-visible reveals.

    btcrpass hands passphrases to its worker processes in chunks sized to a hundredth of a
    second. On a machine with many cores that is small enough that handing them over costs
    more than checking them -- measured on 14 cores, the default ran 2,083/s where 0.05
    seconds per chunk ran 9,370/s. Nothing fails when this regresses; the search is simply
    four times longer, which is invisible unless someone is holding a stopwatch.
    """

    def test_the_search_asks_for_a_longer_chunk(self):
        from btcrecover import btcrpass
        seen = []
        original = btcrpass.parse_arguments

        def spy(*args, **kwds):
            seen.append(btcrpass.chunk_seconds_hint)
            return original(*args, **kwds)

        btcrpass.parse_arguments = spy
        try:
            embed.run(embed.SearchPlan(config()), MNEMONIC)
        finally:
            btcrpass.parse_arguments = original
        self.assertEqual(seen, [embed.CHUNK_SECONDS])
        self.assertGreaterEqual(embed.CHUNK_SECONDS, 0.05)

    def test_the_hint_is_cleared_afterwards(self):
        # it is a module global in btcrpass; leaving it set would follow the next caller
        from btcrecover import btcrpass
        embed.run(embed.SearchPlan(config()), MNEMONIC)
        self.assertIsNone(btcrpass.chunk_seconds_hint)

    def test_the_rate_is_measured_rather_than_assumed(self):
        # the chunk size is derived from est_secs_per_password, so skipping the pre-start
        # benchmark to save 0.13s leaves the wallet's own guess -- off by 8x here -- in
        # charge of it. That trade was measured and is not worth making.
        plan = embed.SearchPlan(config())
        self.assertNotIn("--skip-pre-start", plan._argv(MNEMONIC))


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
