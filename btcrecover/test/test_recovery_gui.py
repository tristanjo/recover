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

    def test_a_seed_word_that_is_not_a_seed_word_is_caught(self):
        """btcrecover substitutes the closest word and says so only in the log.

        A search then runs -- possibly for days -- against a phrase its owner never typed,
        and reports nothing more useful than "not found". The owner can fix their own typo;
        a guess between 'rebel', 'resemble' and 'relief' cannot.
        """
        good = MNEMONIC
        self.assertEqual(recovery_gui.unknown_seed_words(good), [])
        bad = good.replace("about", "reble")
        found = recovery_gui.unknown_seed_words(bad)
        self.assertEqual([w for w, _ in found], ["reble"])
        self.assertIn("rebel", found[0][1])

    def test_case_does_not_make_a_word_unknown(self):
        self.assertEqual(recovery_gui.unknown_seed_words("ABANDON about"), [])

    def test_a_missing_wordlist_does_not_block_the_search(self):
        # if the list cannot be read there is nothing to check against, and refusing to
        # search would be worse than letting btcrecover decide
        original = recovery_gui.seed_wordlist
        recovery_gui.seed_wordlist = lambda *a, **k: None
        try:
            self.assertEqual(recovery_gui.unknown_seed_words("nonsense words here"), [])
        finally:
            recovery_gui.seed_wordlist = original

    def test_the_log_drops_advice_nobody_can_take(self):
        # command-line flags, in a window with no command line, sitting between the lines
        # that do matter
        noisy = ("Detected supplied address types: BIP84 (P2WPKH)\n"
                 "Assuming a 24 word mnemonic. (This can be overridden with --mnemonic-length)\n"
                 "Wallet Type: btcrpass.WalletBIP39\n"
                 "'reble' was in your guess, but it's not a valid seed word;\n"
                 "Pre-start benchmark: measuring. Use --skip-pre-start to skip or ...\n"
                 "Duplicate Check Level: 1 , Add --no-dupchecks up to 4 times fully disable\n"
                 "secp256k1 backend: wallycore")
        tidy = recovery_gui.RecoveryApp._tidy_log(noisy)
        for gone in ("--mnemonic-length", "--skip-pre-start", "--no-dupchecks",
                     "btcrpass.WalletBIP39"):
            self.assertNotIn(gone, tidy)
        # and the two that matter survive
        self.assertIn("not a valid seed word", tidy)
        self.assertIn("secp256k1 backend", tidy)

    def test_humanize(self):
        self.assertEqual(recovery_gui.humanize(45), "45초")
        self.assertEqual(recovery_gui.humanize(300), "5분 0초")
        self.assertEqual(recovery_gui.humanize(0.4), "1초 미만")   # not "0초"
        self.assertEqual(recovery_gui.humanize(90), "1분 30초")
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
        """The answer has to be one somebody else wrote down.

        "TREZOR" looks like a brand name dropped into the screen for no reason, and the
        temptation is to swap it for something plainer. It is the passphrase in BIP39's own
        test vector, and that is the whole point: a customer can look it up somewhere that
        is not us. A value we chose would prove only that the program agrees with itself.
        """
        plan = embed.SearchPlan(recovery_gui.SELF_TEST["config"])
        self.assertIn(recovery_gui.SELF_TEST["passphrase"], list(plan.grammar.generate()))
        self.assertEqual(recovery_gui.SELF_TEST["passphrase"], "TREZOR")
        self.assertEqual(recovery_gui.SELF_TEST["mnemonic"].split()[-1], "about")
        self.assertEqual(recovery_gui.SELF_TEST["mnemonic"].split().count("abandon"), 11)



# Each gate test swaps this out and puts it back; keep the real one to restore.
ROUTE_CHECK = recovery_gui.has_default_route


def read_source():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "..", "recovery_gui.py")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@unittest.skipUnless(can_open_a_window, "no display available")
class Screens(unittest.TestCase):

    def setUp(self):
        # These drive start_search() directly. Without this the confirmation dialog opens
        # and the suite sits waiting for a human -- 164 seconds the first time it happened.
        recovery_gui.has_default_route = lambda: False
        self.addCleanup(setattr, recovery_gui, "has_default_route", ROUTE_CHECK)
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

    def test_the_screen_says_why_the_answer_is_that_word(self):
        # "TREZOR" unexplained reads as an endorsement, or as an arbitrary choice -- either
        # way the check looks weaker than it is
        self.app.show_checks()
        self.app.update_idletasks()
        screen = self._all_text()
        self.assertIn("BIP39 표준", screen)
        self.assertIn("저희가 정한 값이 아니라", screen)

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

    def test_the_count_is_reconcilable_with_the_one_the_page_quoted(self):
        """grammar.count() leaves out the normalization forms; the page's estimate does not.

        Both are right and they measure different things -- the program tries each candidate
        against every distinct Unicode form of it, inside the search rather than as separate
        candidates. Shown side by side without that said, a customer comparing the two
        numbers concludes one of them is wrong, which is the opposite of what showing them
        the count is for.
        """
        self._load()
        screen = self._all_text()
        self.assertIn("{:,}개".format(self.app.plan.candidate_count()), screen)
        self.assertIn("정규화 형태별로 최대 {}번씩".format(len(self.app.plan.normalizations)),
                      screen)

    def test_the_screen_says_the_phrase_is_good(self):
        """Say so when it is right, not only when it is wrong.

        Someone typing twenty-four words they wrote down years ago has no way to know they
        got them in. "체크섬 정상" costs nothing to show and answers the question they are
        actually asking before they commit to a search that runs for days.
        """
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        self.app._count_words()
        self.assertEqual(self.app.seed_state, "ok")
        self.assertIn("체크섬 정상", self.app.seed_status.cget("text"))
        self.assertEqual(str(self.app.seed_status.cget("foreground")), self.app.c["ok"])

    def test_the_screen_names_the_wrong_word(self):
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC.replace("about", "reble"))
        self.app._count_words()
        self.assertEqual(self.app.seed_state, "bad")
        self.assertIn("reble", self.app.seed_status.cget("text"))
        self.assertIn("rebel", self.app.seed_status.cget("text"))
        self.assertEqual(str(self.app.seed_status.cget("foreground")), self.app.c["bad"])

    def test_a_phrase_that_fails_its_checksum_is_refused(self):
        # not a judgement call: it cannot be the phrase that made this wallet, so searching
        # it burns days to reach the one answer known in advance
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC.replace("about", "abandon"))
        shown = []
        original = recovery_gui.messagebox.showerror
        recovery_gui.messagebox.showerror = lambda *a, **k: shown.append(a)
        try:
            self.app.start_search()
        finally:
            recovery_gui.messagebox.showerror = original
        self.assertEqual(len(shown), 1)
        self.assertIn("체크섬", shown[0][1])
        self.assertIsNone(self.app.result)

    def test_checksum_arithmetic(self):
        good = recovery_gui.check_mnemonic(MNEMONIC)
        self.assertEqual(good[0], "ok")
        for bad in (MNEMONIC.replace("about", "abandon"),       # checksum
                    " ".join(MNEMONIC.split()[:11]),            # length
                    MNEMONIC.replace("about", "reble")):        # not a word
            with self.subTest(bad[-20:]):
                self.assertEqual(recovery_gui.check_mnemonic(bad)[0], "bad")
        self.assertEqual(recovery_gui.check_mnemonic("")[0], "empty")
        self.assertEqual(recovery_gui.check_mnemonic(MNEMONIC.upper())[0], "ok")

    def test_the_clipboard_can_be_emptied_and_says_whether_it_was(self):
        """A pasted seed phrase is still in the clipboard afterwards.

        The button reports what happened rather than claiming it: another program can take
        the clipboard straight back, and one that says "비웠습니다" when it did not is worse
        than no button, because someone would stop worrying about it.
        """
        self._load()
        self.app.show_mnemonic()
        self.app.clipboard_clear()
        self.app.clipboard_append(MNEMONIC)
        self.app.update()
        self.app._clear_clipboard()
        self.assertEqual(self.app.clip_status.cget("text"), "비웠습니다.")
        self.assertEqual(str(self.app.clip_status.cget("foreground")), self.app.c["ok"])
        with self.assertRaises(recovery_gui.tk.TclError):
            self.app.clipboard_get()

    def test_it_reports_a_clipboard_that_refilled(self):
        self._load()
        self.app.show_mnemonic()
        original = self.app.clipboard_get
        self.app.clipboard_get = lambda *a, **k: "누군가 다시 채움"
        try:
            self.app._clear_clipboard()
        finally:
            self.app.clipboard_get = original
        self.assertIn("지우지 못했습니다", self.app.clip_status.cget("text"))
        self.assertEqual(str(self.app.clip_status.cget("foreground")), self.app.c["bad"])

    def test_the_screen_admits_what_clearing_cannot_reach(self):
        # clipboard managers keep their own history, and macOS may already have handed the
        # text to another device. Saying so is the difference between a tool and a promise.
        self._load()
        self.app.show_mnemonic()
        self.app.update_idletasks()
        screen = self._all_text()
        self.assertIn("클립보드 기록을 따로 저장하는", screen)
        self.assertIn("다른 애플 기기", screen)

    def test_the_word_count_follows_a_paste(self):
        """A pasted phrase must not leave the counter reading "0 단어".

        The counter hangs off KeyRelease, and a paste produces no key event, so twelve
        words would sit in the field under a label saying none. That reads as "it did not
        go in", and the next thing someone does is retype it by hand.

        The clipboard round-trip itself is not exercised here: Tk needs a mapped, focused
        window for it, which a test window is not. It was checked by hand against a real
        window -- twelve words in, "12 단어" out.
        """
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        self.assertEqual(self.app.word_count.cget("text"), "0 단어")
        # the handler the <<Paste>> binding schedules. Generating the virtual event needs a
        # mapped, focused window, which a test window is not -- so call what it calls, and
        # check separately that the binding is there to call it.
        self.assertTrue(self.app.mnemonic_text.bind("<<Paste>>"),
                        "nothing listens for a paste, so the counter would not follow one")
        self.app._count_words_if_open()
        self.assertEqual(self.app.word_count.cget("text"), "12 단어")

    def test_the_menu_sends_the_event_to_whatever_has_focus(self):
        # the menu item has no widget of its own to act on
        sent = []
        self.app.show_mnemonic()
        self.app.mnemonic_text.focus_set()
        self.app.update()
        original = self.app.focus_get
        self.app.focus_get = lambda: self.app.mnemonic_text
        try:
            self.app.mnemonic_text.event_generate = lambda e, **k: sent.append(e)
            self.app._to_focused("<<Copy>>")
        finally:
            self.app.focus_get = original
            del self.app.mnemonic_text.event_generate
        self.assertEqual(sent, ["<<Copy>>"])

    def test_the_edit_menu_exists_at_all(self):
        name = self.app.cget("menu")
        self.assertTrue(name, "no menu bar, so Cmd+V reaches nothing on macOS")
        submenu = self.app.nametowidget(
            self.app.nametowidget(name).entrycget("편집", "menu"))
        labels = [submenu.entrycget(i, "label") for i in range(submenu.index("end") + 1)
                  if submenu.type(i) == "command"]
        self.assertEqual(labels, ["잘라내기", "복사", "붙여넣기", "전체 선택"])

    def test_a_new_screen_is_repainted(self):
        # Tk 9 on macOS can leave the window showing the previous screen, or nothing, until
        # an event forces a redraw -- and an apparently empty window is a bad thing to hand
        # someone who was told to be careful
        source = read_source()
        self.assertIn("self.after_idle(self._repaint)", source)
        self.assertIn("def _repaint", source)

    def test_mnemonic_screen_counts_words(self):
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", "one two three")
        self.app._count_words()
        self.assertEqual(self.app.word_count.cget("text"), "3 단어")

    def test_colours_follow_the_theme_rather_than_being_written_down(self):
        """Every colour here used to be a light-theme hex.

        ttk draws the window in whatever the system asks for, so on a Mac in dark mode the
        window went dark and the text stayed #555 and #666 -- grey on near-black. Nothing
        failed; it was simply hard to read, which for a program a nervous person is trying
        to follow is its own kind of failure.
        """
        source = read_source()
        self.assertNotIn('foreground="#', source,
                         "a colour is written down again instead of coming from the theme")
        self.assertIn("_install_palette", source)
        for key in ("muted", "dim", "ok", "warn", "bad"):
            self.assertIn(key, self.app.c)
        # and the palette actually differs by theme, rather than being one set with two names
        self.assertNotEqual(self.app.c["muted"], self.app.c["bad"])

    def test_body_text_is_not_the_smallest_the_toolkit_offers(self):
        import tkinter.font as tkfont
        self.assertGreaterEqual(tkfont.nametofont("TkDefaultFont").cget("size"), 12)

    def test_being_online_is_a_question_not_a_lock(self):
        """Someone trying the program out has no seed to protect.

        This used to disable the button and offer a checkbox saying the network reading was
        a false positive -- which made anyone genuinely online claim something untrue to get
        past it. The check belongs at the moment a real seed is about to be searched, and it
        is a question there, asked once, defaulting to no.
        """
        self._load()
        recovery_gui.has_default_route = lambda: True
        try:
            self.app.show_mnemonic()
            self.app.update_idletasks()
            self.assertNotIn("disabled", self.app.start_button.state())
            self.assertIn("네트워크가 아직 연결되어 있습니다", self._all_text())
            self.assertIn("시험 삼아 돌려보는 중이라면", self._all_text())
        finally:
            recovery_gui.has_default_route = ROUTE_CHECK

    def test_starting_while_online_asks_first(self):
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        asked, answer = [], False
        recovery_gui.has_default_route = lambda: True
        original = recovery_gui.messagebox.askokcancel
        recovery_gui.messagebox.askokcancel = lambda *a, **k: (asked.append((a, k)), answer)[1]
        try:
            self.app.start_search()
            self.assertEqual(len(asked), 1, "no confirmation was asked for")
            self.assertIs(self.app.result, None, "the search started despite a refusal")
            # defaults to cancel: a stray Return must not start a search on a live network
            self.assertEqual(asked[0][1].get("default"), recovery_gui.messagebox.CANCEL)
        finally:
            recovery_gui.messagebox.askokcancel = original
            recovery_gui.has_default_route = ROUTE_CHECK

    def test_offline_starts_without_asking(self):
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        asked = []
        recovery_gui.has_default_route = lambda: False
        original = recovery_gui.messagebox.askokcancel
        recovery_gui.messagebox.askokcancel = lambda *a, **k: asked.append(1) or True
        try:
            self.app.start_search()
            self._wait_for_result()
            self.assertFalse(asked, "asked about a network that is not there")
            self.assertTrue(self.app.result.found)
        finally:
            recovery_gui.messagebox.askokcancel = original
            recovery_gui.has_default_route = ROUTE_CHECK

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

    def test_success_tells_them_what_to_do_next_not_just_that_it_is_risky(self):
        """Nobody can prove a seed did not leak. What can be done is make a leak worthless.

        That is an action, taken by the customer, in the minutes after this screen appears
        -- and this is the last screen anyone reads. So it has to say the steps, not just
        that there is a risk.
        """
        self._load()
        self.app.show_mnemonic()
        self.app.mnemonic_text.insert("1.0", MNEMONIC)
        self.app.start_search()
        self._wait_for_result()
        screen = self._all_text()
        self.assertIn("지금 해야 할 일", screen)
        for step in ("새 지갑", "보냅니다", "종이에"):
            self.assertIn(step, screen)

        # Broadcasting needs a network, so this cannot end offline -- but it must not be
        # *this* machine that reconnects. Telling someone to plug the computer that just
        # held their seed back in, and then race, is the wrong instruction: a hardware
        # wallet signs on the device, so the seed never reaches an online computer.
        self.assertIn("계속 오프라인", screen)
        self.assertIn("하드웨어 지갑", screen)
        self.assertNotIn("인터넷을 다시 연결하고", screen)

        # The broadcasting device holds no key, so it cannot steal -- but it can show one
        # address and send to another. Verifying on the device's own screen is the only
        # defence and the step people skip, so it has to be on this screen in its own right.
        self.assertIn("하드웨어 지갑 화면에서 직접 확인", screen)

        # A hop through a phone wallet on the way is worse, not better: two fees, and the
        # coins sit under a key held on a networked device in between.
        self.assertIn("한 번에", screen)

        # And someone with no hardware wallet still needs an answer today; if the seed did
        # leak, waiting for delivery is not a neutral choice.
        self.assertIn("하드웨어 지갑이 없다면", screen)

        # and it must not claim more than it can: no promise that nothing leaked
        self.assertNotIn("안전합니다", screen)

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
        # These drive start_search() directly. Without this the confirmation dialog opens
        # and the suite sits waiting for a human -- 164 seconds the first time it happened.
        recovery_gui.has_default_route = lambda: False
        self.addCleanup(setattr, recovery_gui, "has_default_route", ROUTE_CHECK)
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
