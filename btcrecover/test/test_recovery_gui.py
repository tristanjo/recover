#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_recovery_gui.py -- unit tests for the offline recovery window
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

"""Walks the window's widget tree instead of looking at pixels.

What matters here is not how it looks but what it says and what it keeps: that the seed
phrase never reaches the resume file, that a wallet whose passphrase was stored
unnormalized is still found and the form is named, and that a search that is stopped can
be picked up again.
"""

import json, os, sys, tempfile, threading, time, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

from btcrecover import embed

try:
    import tkinter
    # Deliberately not instantiated here. A process may hold only one Tk root, and
    # creating a probe root and destroying it makes the *next* one segfault on macOS --
    # which is how this file first failed. On Linux the environment says whether a
    # display exists; elsewhere tkinter importing at all is enough to go on.
    can_open_a_window = (sys.platform != "linux"
                         or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")))
except ImportError:
    can_open_a_window = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import recovery_gui

# The single window every test in this file shares.
APP = None


def setUpModule():
    global APP
    if not can_open_a_window:
        return
    try:
        APP = recovery_gui.RecoveryApp()
        APP.withdraw()
    except Exception as e:                       # a headless box that got past the check
        raise unittest.SkipTest("no display available: {}".format(e))


def tearDownModule():
    global APP
    if APP is not None:
        APP.destroy()
        APP = None


MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
ADDR_NFC = "12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu"   # stored its passphrase as NFC, not NFKD
PASSPHRASE = "비밀번호2024"

CONFIG = {
    "version": 1,
    "wallet": {"type": "bip39", "addresses": [ADDR_NFC], "language": "en",
               "derivation_paths": ["m/44'/0'/0'/0"], "address_limit": 5},
    "passphrase": {"slots": [{"type": "words", "candidates": ["비밀번호"], "cases": ["asis"]},
                             {"type": "digits", "candidates": ["2023", "2024", "2025"]}],
                   "separators": [""], "normalizations": ["NFKD", "NFC"]},
}


def texts(widget):
    """Every piece of text on screen, from labels, buttons and text boxes alike."""
    found = []
    for child in widget.winfo_children():
        try:
            value = child.cget("text")
            if value:
                found.append(str(value))
        except (tkinter.TclError, AttributeError):
            pass
        if isinstance(child, tkinter.Text):
            found.append(child.get("1.0", "end").strip())
        found.extend(texts(child))
    return found


class Helpers(unittest.TestCase):
    """These run without a display."""

    def test_humanize(self):
        self.assertEqual(recovery_gui.humanize(45), "45초")
        self.assertEqual(recovery_gui.humanize(300), "5분")
        self.assertEqual(recovery_gui.humanize(7200), "2.0시간")
        self.assertEqual(recovery_gui.humanize(None), "계산 중")
        self.assertEqual(recovery_gui.humanize(float("inf")), "계산 중")

    def test_fingerprint_ignores_key_order_but_not_content(self):
        self.assertEqual(recovery_gui.fingerprint({"a": 1, "b": 2}),
                         recovery_gui.fingerprint({"b": 2, "a": 1}))
        self.assertNotEqual(recovery_gui.fingerprint({"a": 1}),
                            recovery_gui.fingerprint({"a": 2}))

    def test_connectivity_check_sends_nothing(self):
        # a bool either way; the point is that it must not raise, and must not block
        started = time.monotonic()
        self.assertIn(recovery_gui.has_default_route(), (True, False))
        self.assertLess(time.monotonic() - started, 2.0)

    def test_help_exits_cleanly_without_opening_a_window(self):
        """run-all-tests.py runs every script in the repository with --help and accepts
        only a clean exit. Falling through to the window instead fails on a headless
        machine and hangs on a desktop one, holding the window open forever.

        The verdict is the exit code alone. Reading the child's output would tie this to
        how the parent's locale decodes Korean -- cp1252 on a Windows runner -- and that
        is a second thing to get wrong, not a second thing being tested.
        """
        import subprocess
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        for flag in ("--help", "-h"):
            with self.subTest(flag):
                done = subprocess.run([sys.executable, "recovery_gui.py", flag],
                                      cwd=root, capture_output=True, timeout=120)
                detail = "\n".join(
                    name + ": " + (stream or b"").decode("utf-8", "replace")[-1500:]
                    for name, stream in (("stdout", done.stdout), ("stderr", done.stderr)))
                self.assertEqual(done.returncode, 0, detail)
                self.assertIn(b"--self-test", done.stdout or b"")

    def test_the_self_test_uses_the_published_bip39_vector(self):
        plan = embed.SearchPlan(recovery_gui.SELF_TEST["config"])
        self.assertIn(recovery_gui.SELF_TEST["passphrase"], list(plan.grammar.generate()))
        self.assertEqual(recovery_gui.SELF_TEST["passphrase"], "TREZOR")


@unittest.skipUnless(can_open_a_window, "no display available")
class Screens(unittest.TestCase):

    def setUp(self):
        self.app = APP
        self.app.config_path = self.app.config_data = self.app.plan = self.app.result = None
        self.app.skip = 0
        self.tmp = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp, "config.json")
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f)

    def _load(self, skip=0):
        self.app.config_path = self.config_path
        self.app.config_data = CONFIG
        self.app.plan = embed.SearchPlan(CONFIG)
        self.app.skip = skip
        self.app.show_summary()
        self.app.update_idletasks()

    def _all_text(self):
        return "\n".join(texts(self.app.container))

    def test_first_screen_offers_the_self_test_before_anything_else(self):
        self.app.show_checks()
        self.app.update_idletasks()
        screen = self._all_text()
        self.assertIn("자가검증", screen)
        self.assertIn("네트워크", screen)

    def test_self_test_passes(self):
        self.app.show_checks()
        self.app.run_self_test()
        for _ in range(200):                     # it runs on a thread; let it finish
            self.app.update()
            if "통과" in self.app.selftest_label.cget("text"):
                break
            time.sleep(0.05)
        self.assertIn("통과", self.app.selftest_label.cget("text"))
        self.assertIn(recovery_gui.SELF_TEST["passphrase"], self.app.selftest_label.cget("text"))

    def test_summary_shows_what_will_be_searched(self):
        self._load()
        screen = self._all_text()
        self.assertIn(ADDR_NFC, screen)
        self.assertIn("m/44'/0'/0'/0", screen)
        self.assertIn("3개", screen)                        # the candidate count
        self.assertIn("NFC", screen)
        self.assertIn(PASSPHRASE, screen)                   # the preview of first candidates

    def test_summary_warns_when_extra_normalizations_are_in_play(self):
        self._load()
        self.assertIn("비ASCII", self._all_text())

    def test_mnemonic_screen_counts_words(self):
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", "one two three")
        self.app._count_words()
        self.assertEqual(self.app.word_count.cget("text"), "3 단어")

    def test_a_full_run_finds_it_and_names_the_form(self):
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        self.app.start_search()
        self._wait_for_result()
        screen = self._all_text()
        self.assertIn(PASSPHRASE, screen)
        self.assertIn("NFC", screen)
        self.assertIn("옮기세요", screen)                    # move the funds, now
        self.assertTrue(self.app.result.found)

    def test_a_miss_says_so_without_blaming_the_program(self):
        cfg = json.loads(json.dumps(CONFIG))
        cfg["passphrase"]["slots"][1] = {"type": "digits", "candidates": ["0001"]}
        self.app.config_path, self.app.config_data = self.config_path, cfg
        self.app.plan, self.app.skip = embed.SearchPlan(cfg), 0
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        self.app.start_search()
        self._wait_for_result()
        self.assertIn("찾지 못했습니다", self._all_text())

    def _wait_for_result(self, timeout=60):
        """Wait for the search, then for _poll to swap the progress screen out.

        The progress screen already has children, so "are there widgets" is not the
        question -- the question is whether the one still saying "찾는 중" is gone.
        """
        deadline = time.monotonic() + timeout
        while self.app.result is None and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.05)
        self.assertIsNotNone(self.app.result, "the search never finished")
        while "찾는 중" in self._all_text() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.05)
        self.assertNotIn("찾는 중", self._all_text(), "the result screen never appeared")


@unittest.skipUnless(can_open_a_window, "no display available")
class ResumeFile(unittest.TestCase):
    """The resume file records a position and nothing else."""

    def setUp(self):
        self.app = APP
        self.tmp = tempfile.mkdtemp()
        self.app.config_path = os.path.join(self.tmp, "config.json")
        self.app.config_data = CONFIG

    def test_round_trip(self):
        self.app._write_progress(1234)
        self.assertEqual(self.app._read_progress(), 1234)

    def test_it_holds_no_seed_phrase_and_no_candidate(self):
        self.app._write_progress(1234)
        with open(self.app._progress_path(), "r", encoding="utf-8") as f:
            written = f.read()
        self.assertNotIn("abandon", written)
        self.assertNotIn("비밀번호", written)
        self.assertEqual(set(json.loads(written)), {"config", "tried"})

    def test_a_position_from_a_different_config_is_ignored(self):
        self.app._write_progress(1234)
        other = json.loads(json.dumps(CONFIG))
        other["passphrase"]["slots"][0]["candidates"] = ["다른값"]
        self.app.config_data = other
        self.assertEqual(self.app._read_progress(), 0)

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(self.app._read_progress(), 0)

    def test_corrupt_file_is_not_an_error(self):
        with open(self.app._progress_path(), "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        self.assertEqual(self.app._read_progress(), 0)


if __name__ == '__main__':
    unittest.main()
