#!/usr/bin/env python
# -*- coding: utf-8 -*-

# recovery_gui.py -- offline passphrase recovery, for someone who is not at a terminal
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

"""A four-screen window: check, load, enter the seed phrase, watch it run.

Everything the search needs beyond the seed phrase arrives in a config.json written
elsewhere. The seed phrase is typed here, held in memory, and never written anywhere --
not to the resume file, not to a log, not to the screen after the window closes.

This program makes no network request of any kind. The connectivity check reads the
local routing table without sending a packet; see `has_default_route`.
"""

import difflib, hashlib, json, os, queue, socket, sys, threading, time, tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

from btcrecover import embed

# The published BIP39 test vector. Used by the self-test so someone can watch the program
# find a known answer -- and watch their network monitor stay silent -- before trusting it
# with their own seed phrase.
SELF_TEST = {
    "mnemonic": "abandon abandon abandon abandon abandon abandon abandon abandon "
                "abandon abandon abandon about",
    "passphrase": "TREZOR",
    "config": {
        "wallet": {"type": "bip39", "addresses": ["1PEha8dk5Me5J1rZWpgqSt5F4BroTBLS5y"],
                   "derivation_paths": ["m/44'/0'/0'/0"], "address_limit": 2, "language": "en"},
        "passphrase": {"slots": [{"type": "words",
                                  "candidates": ["NOT-IT", "TREZOR", "ALSO-NOT-IT"],
                                  "cases": ["asis"]}],
                       "separators": [""], "normalizations": ["NFKD"]},
    },
}

PAD = 18


def has_default_route():
    """Whether this machine could reach a network, without touching one.

    connect() on a UDP socket transmits nothing; it only asks the operating system which
    local address a packet *would* leave from. The address below is TEST-NET-1 (RFC 5737),
    which exists precisely so it can be written down without referring to anyone's server.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return True
    except OSError:
        return False
    finally:
        probe.close()


WORDLISTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "btcrecover", "wordlists")


def seed_wordlist(language="en"):
    """The BIP39 words for a language, or None if the list is not there."""
    path = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
                        "btcrecover", "wordlists", "bip39-{}.txt".format(language or "en"))
    if not os.path.isfile(path):
        path = os.path.join(WORDLISTS, "bip39-{}.txt".format(language or "en"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [w.strip() for w in f if w.strip() and not w.startswith("#")]
    except OSError:
        return None


def unknown_seed_words(mnemonic, language="en"):
    """Words that are not in the BIP39 list, each with the closest ones that are.

    btcrecover does not stop for these -- it substitutes whatever is closest and prints a
    line saying so, which in this window lands in a log box nobody opens. So a search can
    run for days against a seed phrase the owner never typed, fail, and report only that
    the passphrase was not found.

    Catching it here lets the owner fix their own typo, which they can do and a guess
    cannot: 'reble' is one edit from 'rebel', and also from 'resemble' and 'relief'.
    """
    words = seed_wordlist(language)
    if not words:
        return []                      # no list to check against; let btcrecover decide
    known = set(words)
    out = []
    for word in mnemonic.split():
        if word.lower() not in known:
            out.append((word, difflib.get_close_matches(word.lower(), words, 3, 0.6)))
    return out


SEED_LENGTHS = (12, 15, 18, 21, 24)


def check_mnemonic(mnemonic, language="en"):
    """Is this a well-formed BIP39 seed phrase? Returns (state, message).

    `state` is "empty", "bad" or "ok". Checked here, while it is being typed, rather than
    after the search: btcrecover substitutes the closest word for anything it does not
    recognise and says so only in its log, so a phrase with one wrong word runs to the end
    against a seed its owner never had and reports only that nothing was found.

    The checksum is the part worth having. Every valid phrase carries a few bits derived
    from the rest of it, so a single wrong or swapped word almost always fails it. Being
    told that now costs a second; being told nothing costs the whole search.
    """
    words = mnemonic.split()
    if not words:
        return "empty", ""

    wordlist = seed_wordlist(language)
    if not wordlist:
        return "unknown", "단어 목록을 읽지 못해 확인을 건너뜁니다."

    index = {w: i for i, w in enumerate(wordlist)}
    missing = [w for w in words if w.lower() not in index]
    if missing:
        near = difflib.get_close_matches(missing[0].lower(), wordlist, 1, 0.6)
        return "bad", "'{}' 은(는) BIP39 단어가 아닙니다{}".format(
            missing[0], " — 혹시 '{}'인가요?".format(near[0]) if near else ".")

    if len(words) not in SEED_LENGTHS:
        return "bad", "{}단어입니다. 시드 문구는 {} 단어여야 합니다.".format(
            len(words), " / ".join(str(n) for n in SEED_LENGTHS))

    # every word is 11 bits; the last few of them are a hash of the rest
    bits = "".join(bin(index[w.lower()])[2:].zfill(11) for w in words)
    check_len = len(words) // 3
    entropy, checksum = bits[:-check_len], bits[-check_len:]
    digest = hashlib.sha256(int(entropy, 2).to_bytes(len(entropy) // 8, "big")).digest()
    expected = bin(digest[0])[2:].zfill(8)[:check_len]
    if checksum != expected:
        return "bad", ("체크섬이 맞지 않습니다. 단어 하나가 틀렸거나 순서가 바뀌었을 "
                       "가능성이 높습니다.")
    return "ok", "{}단어 · 모두 BIP39 단어 · 체크섬 정상".format(len(words))


def fingerprint(config):
    """Identifies a config, so a resume file cannot be applied to a different search."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def humanize(seconds):
    if seconds is None or seconds != seconds or seconds == float("inf"):
        return "계산 중"
    if seconds < 1:       return "1초 미만"      # "0초 만에 찾았습니다" reads as a bug
    seconds = int(seconds)
    if seconds < 60:      return "{}초".format(seconds)
    if seconds < 3600:    return "{}분 {}초".format(seconds // 60, seconds % 60)
    if seconds < 172800:  return "{:.1f}시간".format(seconds / 3600)
    if seconds < 63072000: return "{:.1f}일".format(seconds / 86400)
    return "{:,}년".format(int(seconds / 31557600))


class RecoveryApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("패스프레이즈 복구")
        self.geometry("720x560")
        self.minsize(640, 520)

        self._install_palette()
        self._install_fonts()
        self._install_menu()
        self.config_path = None
        self.config_data = None
        self.plan = None
        self.skip = 0
        self.abort = None
        self.progress_state = (0, 0)
        self.result = None
        self.selftest_result = None
        self.started_at = None

        container = ttk.Frame(self, padding=PAD)
        container.pack(fill="both", expand=True)
        self.container = container
        self.show_checks()

    def _install_menu(self):
        """An Edit menu, which is what makes Cmd+V work at all.

        Tk on macOS delivers Command-key shortcuts through the menu bar. With no Edit menu
        there is nothing to deliver them to, so Cmd+V does nothing in every text field --
        and the seed phrase field is the one place where that matters most. Twenty-four
        words typed by hand is twenty-four chances to get one wrong, and a wrong word means
        a search that cannot succeed and gives no hint why.

        The items fire Tk's virtual events, so the same menu drives Ctrl+V elsewhere.
        """
        bar = tk.Menu(self)
        edit = tk.Menu(bar, tearoff=0)
        for label, event in (("잘라내기", "<<Cut>>"), ("복사", "<<Copy>>"),
                             ("붙여넣기", "<<Paste>>")):
            edit.add_command(
                label=label, accelerator="Cmd+" + label[0],
                command=lambda e=event: self._to_focused(e))
        edit.add_separator()
        edit.add_command(label="전체 선택", command=lambda: self._select_all())
        bar.add_cascade(label="편집", menu=edit)
        try:
            self.config(menu=bar)
        except tk.TclError:
            pass                      # a platform without a menu bar; the field still works

    def _to_focused(self, virtual_event):
        widget = self.focus_get()
        if widget is not None:
            widget.event_generate(virtual_event)
            self.after_idle(self._count_words_if_open)

    def _select_all(self):
        widget = self.focus_get()
        if isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end-1c")
        elif widget is not None:
            try:
                widget.selection_range(0, "end")
            except (tk.TclError, AttributeError):
                pass

    def _count_words_if_open(self):
        # a paste puts no key event in front of the counter, so it would sit at "0 단어"
        # next to a field with twelve words in it
        if getattr(self, "word_count", None) and self.word_count.winfo_exists():
            self._count_words()

    def _install_palette(self):
        """Colours picked from the theme rather than written down.

        Every colour here used to be a light-theme hex. On a Mac in dark mode ttk draws the
        window dark and the text stayed #555 and #666 -- grey on near-black, which is where
        the readability went. Ask the theme what it is actually drawing, then pick a set
        that can be read on it.
        """
        try:
            background = ttk.Style().lookup("TLabel", "background") or self.cget("background")
            r, g, b = (v / 65535.0 for v in self.winfo_rgb(background))
            dark = (0.2126 * r + 0.7152 * g + 0.0722 * b) < 0.5
        except tk.TclError:
            dark = False
        self.dark = dark
        self.c = {
            "muted": "#a9a5b3" if dark else "#4b4843",   # secondary text
            "dim":   "#8f8b99" if dark else "#5f5c55",   # status lines, captions
            "ok":    "#4ade80" if dark else "#15803d",
            "warn":  "#fbbf24" if dark else "#a16207",
            "bad":   "#f87171" if dark else "#b91c1c",
            "accent": "#a78bfa" if dark else "#6d28d9",
        }

    def _install_fonts(self):
        families = set(tkfont.families())
        for name in ("Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", "NanumGothic"):
            if name in families:
                for style in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
                    tkfont.nametofont(style).configure(family=name)
                break
        tkfont.nametofont("TkDefaultFont").configure(size=12)
        self.title_font = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.title_font.configure(size=16, weight="bold")
        self.mono = tkfont.Font(family="Consolas" if "Consolas" in families else "Courier", size=13)
        self.bold = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.bold.configure(size=13, weight="bold")
        # The one line a customer must not skim past gets its own size.
        self.huge = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.huge.configure(size=34, weight="bold")
        self.small = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.small.configure(size=11)
        self.alarm = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.alarm.configure(size=15, weight="bold")

    def _icon(self, parent, kind, size=28):
        """A warning triangle or an all-clear tick, drawn rather than typed.

        A Unicode glyph would be one line, but whether it arrives as a symbol or as an
        empty box depends on which fonts the customer's Windows happens to have. Drawing
        it means it looks the same on every machine, which for the one warning that
        matters most is worth the extra lines.
        """
        try:
            background = ttk.Style().lookup("TLabelframe", "background") or None
        except tk.TclError:
            background = None
        canvas = tk.Canvas(parent, width=size, height=size, highlightthickness=0,
                           borderwidth=0, background=background or self.cget("background"))
        pad, mid = size * 0.08, size / 2.0
        if kind == "warn":
            canvas.create_polygon(mid, pad, size - pad, size - pad * 1.6, pad, size - pad * 1.6,
                                  fill="#dc2626", outline="#991b1b", width=1)
            canvas.create_line(mid, size * 0.34, mid, size * 0.63,
                               fill="white", width=max(2, int(size * 0.10)), capstyle="round")
            canvas.create_oval(mid - size * 0.055, size * 0.71, mid + size * 0.055, size * 0.82,
                               fill="white", outline="")
        else:
            canvas.create_oval(pad, pad, size - pad, size - pad,
                               fill="#16a34a", outline="#15803d", width=1)
            canvas.create_line(size * 0.28, mid, size * 0.44, size * 0.66, size * 0.73, size * 0.34,
                               fill="white", width=max(2, int(size * 0.11)),
                               capstyle="round", joinstyle="round")
        return canvas

    # ---- screen plumbing -------------------------------------------------

    def _clear(self):
        """Empty the container, and make sure whatever replaces it actually gets painted.

        Every screen is built by destroying the previous one and packing a new set of
        widgets. On macOS with Tk 9 that can leave the window showing the old content, or
        nothing, until some event arrives -- a click, a resize -- and forces a redraw. The
        program is not stuck and nothing has failed, but the person in front of it has no
        way to know that, and clicking an apparently empty window to see what happens is a
        bad thing to ask of someone who was told to be careful.

        after_idle runs once the caller has finished packing the new screen, so this is one
        place rather than one line at the end of all five.
        """
        for child in self.container.winfo_children():
            child.destroy()
        self.after_idle(self._repaint)

    def _repaint(self):
        try:
            self.update_idletasks()
        except tk.TclError:
            pass                      # the window went away between the schedule and now

    def _heading(self, text, subtitle=None):
        ttk.Label(self.container, text=text, font=self.title_font).pack(anchor="w")
        if subtitle:
            ttk.Label(self.container, text=subtitle, foreground=self.c["dim"],
                      wraplength=640, justify="left").pack(anchor="w", pady=(4, PAD))
        else:
            ttk.Frame(self.container, height=PAD).pack()

    # ---- 1. checks -------------------------------------------------------

    def show_checks(self):
        self._clear()
        self._heading("복구 준비", "시작하기 전에 두 가지를 확인합니다.")

        online = has_default_route()
        box = ttk.LabelFrame(self.container, text=" 1. 네트워크 연결 ", padding=12)
        box.pack(fill="x", pady=(0, 12))
        if online:
            ttk.Label(box, foreground=self.c["warn"], wraplength=620, justify="left",
                      text="이 컴퓨터는 아직 네트워크에 연결되어 있습니다.\n"
                           "랜선을 뽑고 Wi-Fi를 끈 뒤 [다시 확인]을 눌러 주세요. "
                           "이 프로그램은 네트워크를 쓰지 않지만, 같은 컴퓨터의 다른 프로그램은 "
                           "그렇지 않을 수 있습니다.").pack(anchor="w")
            ttk.Button(box, text="다시 확인", command=self.show_checks).pack(anchor="w", pady=(8, 0))
        else:
            ttk.Label(box, foreground=self.c["ok"],
                      text="네트워크에 연결되어 있지 않습니다. 좋습니다.").pack(anchor="w")

        box2 = ttk.LabelFrame(self.container, text=" 2. 동작 자가검증 ", padding=12)
        box2.pack(fill="x", pady=(0, 12))
        ttk.Label(box2, wraplength=620, justify="left",
                  # The answer being "TREZOR" is not a choice and not an endorsement -- it
                  # is the passphrase written into the BIP39 specification's own test
                  # vector, which is the entire reason this check is worth running. A value
                  # we picked ourselves would only prove the program agrees with itself.
                  text="BIP39 표준 문서에 실린 공개 시험값으로 계산이 맞는지 확인합니다.\n"
                       "본인의 시드 문구를 넣기 전에 먼저 돌려 보세요. 이 검증에는 본인 정보가 "
                       "전혀 쓰이지 않습니다.\n"
                       "답이 'TREZOR' 인 것은 저희가 정한 값이 아니라 BIP39 표준에 그렇게 적혀 "
                       "있기 때문입니다. 그래서 이 결과는 다른 곳에서도 대조해볼 수 있습니다 — "
                       "저희가 고른 값이었다면 프로그램이 제 말에 동의한다는 것밖에 증명하지 "
                       "못합니다.").pack(anchor="w")
        self.selftest_label = ttk.Label(box2, text="", foreground=self.c["dim"])
        self.selftest_label.pack(anchor="w", pady=(8, 0))
        self.selftest_button = ttk.Button(box2, text="자가검증 실행", command=self.run_self_test)
        self.selftest_button.pack(anchor="w", pady=(8, 0))

        ttk.Label(self.container, foreground=self.c["muted"], wraplength=640, justify="left",
                  text="이 프로그램은 어떤 네트워크 요청도 하지 않습니다. 위의 연결 확인은 "
                       "패킷을 보내지 않고 운영체제의 경로표만 읽습니다.").pack(anchor="w", pady=(4, 12))

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x")
        ttk.Button(nav, text="설정 파일 열기  →", command=self.load_config).pack(side="right")

    def run_self_test(self):
        self.selftest_button.state(["disabled"])
        self.selftest_label.configure(text="실행 중...", foreground=self.c["dim"])
        self.selftest_result = None

        def work():
            try:
                plan = embed.SearchPlan(SELF_TEST["config"])
                self.selftest_result = embed.run(plan, SELF_TEST["mnemonic"])
            except Exception as e:                      # a failed self-test must still report
                self.selftest_result = embed.SearchResult(error=str(e))

        threading.Thread(target=work, daemon=True).start()
        self.after(100, self._poll_self_test)

    def _poll_self_test(self):
        # Tk's after() is not safe to call from another thread, so the worker leaves its
        # result in an attribute and this, on the main thread, comes looking for it.
        if not self.selftest_label.winfo_exists():
            return                                      # the user moved on
        if self.selftest_result is None:
            self.after(100, self._poll_self_test)
            return
        self._self_test_done(self.selftest_result)

    def _self_test_done(self, result):
        self.selftest_button.state(["!disabled"])
        if result.found and result.passphrase == SELF_TEST["passphrase"]:
            self.selftest_label.configure(
                text="통과 — 표준 문서에 적힌 답 '{}' 을 {:.1f}초 만에 찾았습니다.".format(
                    result.passphrase, result.elapsed), foreground=self.c["ok"])
        else:
            self.selftest_label.configure(
                text="실패 — " + (result.error or "정답을 찾지 못했습니다") +
                     "\n이 상태로는 본인 시드를 넣지 마세요.", foreground=self.c["bad"])

    # ---- 2. config -------------------------------------------------------

    def load_config(self):
        path = filedialog.askopenfilename(
            title="config.json 선택", filetypes=[("설정 파일", "*.json"), ("모든 파일", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            plan = embed.SearchPlan(data)
        except Exception as e:
            messagebox.showerror("설정 파일을 읽을 수 없습니다", str(e))
            return

        self.config_path, self.config_data, self.plan = path, data, plan
        self.skip = self._offer_resume()
        self.show_summary()

    def _offer_resume(self):
        saved = self._read_progress()
        if not saved:
            return 0
        if messagebox.askyesno(
                "이어서 하기",
                "이전에 {:,}개까지 확인한 기록이 있습니다.\n이어서 진행할까요?\n\n"
                "[아니오]를 누르면 처음부터 다시 시작합니다.".format(saved)):
            return saved
        return 0

    def _progress_path(self):
        return self.config_path + ".progress" if self.config_path else None

    def _read_progress(self):
        path = self._progress_path()
        if not path or not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("config") != fingerprint(self.config_data):
                return 0        # a different search; its position means nothing here
            return max(0, int(saved.get("tried", 0)))
        except (OSError, ValueError):
            return 0

    def _write_progress(self, tried):
        """Records only how far the search got. Never the seed phrase or a candidate."""
        path = self._progress_path()
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"config": fingerprint(self.config_data), "tried": int(tried)}, f)
        except OSError:
            pass                # losing the resume point is not worth interrupting for

    def show_summary(self):
        self._clear()
        plan, total = self.plan, self.plan.candidate_count()
        self._heading("설정 확인", os.path.basename(self.config_path))

        grid = ttk.Frame(self.container)
        grid.pack(fill="x", pady=(0, 12))
        rows = [
            ("확인할 지갑 주소", "\n".join(plan.addresses)),
            ("파생 경로", "  ".join(plan.derivation_paths)),
            ("주소 탐색 개수", str(plan.address_limit)),
            ("시도할 패스프레이즈", "{:,}개{}".format(
                total,
                "" if len(plan.normalizations) < 2 else
                "  (정규화 형태별로 최대 {}번씩)".format(len(plan.normalizations)))),
            ("유니코드 정규화", ", ".join(plan.normalizations)),
        ]
        if plan.of > 1:
            # Say it here, before the search starts, and again if it finds nothing. Someone
            # who forgets they are running a seventh of the work will read "not found" as
            # "the passphrase is not in this range", which is the wrong conclusion and the
            # expensive one -- they stop.
            rows.insert(3, ("나눠 돌리는 중",
                            "전체 {:,}개 중 {}번째 구간 ({}개로 분할)".format(
                                plan.total_count(), plan.part, plan.of)))
        if self.skip:
            rows.append(("이어서 시작", "{:,}번째부터 (남은 {:,}개)".format(self.skip, total - self.skip)))
        for i, (label, value) in enumerate(rows):
            ttk.Label(grid, text=label, foreground=self.c["muted"]).grid(row=i, column=0, sticky="nw", pady=3)
            ttk.Label(grid, text=value, wraplength=460, justify="left").grid(
                row=i, column=1, sticky="w", padx=(16, 0), pady=3)

        if len(plan.normalizations) > 1:
            ttk.Label(self.container, foreground=self.c["warn"], wraplength=640, justify="left",
                      text="패스프레이즈에 한글 등 비ASCII 문자가 있어, 지갑이 저장했을 수 있는 "
                           "여러 유니코드 형태를 모두 시도합니다.").pack(anchor="w", pady=(0, 12))

        preview = ttk.LabelFrame(self.container, text=" 처음 시도할 후보 ", padding=10)
        preview.pack(fill="x", pady=(0, 12))
        sample = list(plan.grammar.generate(skip=self.skip, limit=5))
        ttk.Label(preview, text="\n".join(sample) or "(없음)", font=self.mono,
                  justify="left").pack(anchor="w")

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x")
        ttk.Button(nav, text="←  뒤로", command=self.show_checks).pack(side="left")
        ttk.Button(nav, text="시드 문구 입력  →", command=self.show_mnemonic).pack(side="right")

    # ---- 3. the seed phrase ---------------------------------------------

    def show_mnemonic(self):
        self._clear()
        self._heading("시드 문구 입력",
                      "지갑을 만들 때 적어 둔 단어들을 순서대로 띄어쓰기로 구분해 입력하세요. "
                      "이 문구는 이 컴퓨터의 메모리에만 있으며 어디에도 저장되지 않습니다.")

        self.mnemonic_text = tk.Text(self.container, height=5, wrap="word", font=self.mono)
        self.mnemonic_text.pack(fill="x", pady=(0, 6))
        self.mnemonic_text.focus_set()

        status = ttk.Frame(self.container)
        status.pack(fill="x")
        self.word_count = ttk.Label(status, text="0 단어", foreground=self.c["muted"])
        self.word_count.pack(side="left", padx=(0, 10))
        # Checked while it is being typed. Told now, a wrong word costs a second; told
        # nothing, it costs the whole search and explains nothing at the end of it.
        self.seed_status = ttk.Label(status, text="", font=self.bold)
        self.seed_status.pack(side="left")
        self.mnemonic_text.bind("<KeyRelease>", self._count_words)
        # Ctrl+V and the menu both raise this; without it a pasted phrase reads "0 단어"
        self.mnemonic_text.bind("<<Paste>>",
                                lambda _e: self.after_idle(self._count_words_if_open))

        ttk.Label(self.container, foreground=self.c["warn"], wraplength=640, justify="left",
                  text="복구에 성공하면 자금을 곧바로 새 지갑으로 옮기세요. 이 시드 문구는 "
                       "복구 과정에서 이 컴퓨터의 메모리를 거치므로 더 이상 안전하다고 볼 수 "
                       "없습니다. 이 컴퓨터를 다시 인터넷에 연결할 필요는 없습니다 \u2014 "
                       "하드웨어 지갑에 복구한 뒤 다른 기기에서 보내면 됩니다. 자세한 순서는 "
                       "찾은 뒤에 안내합니다."
                  ).pack(anchor="w", pady=(12, 0))

        # This is the only screen where a secret is typed, so this is where the network
        # check has to bite. The screen before it warns and lets you carry on, which is
        # right -- a config file holds no secret and there is nothing to protect yet.
        self.gate = ttk.Frame(self.container)
        self.gate.pack(fill="x", pady=(12, 0))
        self.start_button = None
        self._render_gate()

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x")
        ttk.Button(nav, text="←  뒤로", command=self.show_summary).pack(side="left")
        self.start_button = ttk.Button(nav, text="찾기 시작", command=self.start_search)
        self.start_button.pack(side="right")
        self._apply_gate()

    def _render_gate(self):
        """The network gate, redrawn whenever it is re-checked."""
        for child in self.gate.winfo_children():
            child.destroy()
        if not has_default_route():
            ok = ttk.Frame(self.gate)
            ok.pack(fill="x")
            self._icon(ok, "ok", 24).pack(side="left", padx=(0, 9))
            ttk.Label(ok, foreground=self.c["ok"], font=self.bold,
                      text="네트워크에 연결되어 있지 않습니다").pack(side="left")
            return

        box = ttk.LabelFrame(self.gate, text=" 네트워크 확인 ", padding=12)
        box.pack(fill="x")
        head = ttk.Frame(box)
        head.pack(fill="x")
        self._icon(head, "warn", 30).pack(side="left", padx=(0, 11), anchor="n")
        said = ttk.Frame(head)
        said.pack(side="left", fill="x", expand=True)
        ttk.Label(said, foreground=self.c["bad"], font=self.alarm,
                  text="네트워크가 아직 연결되어 있습니다").pack(anchor="w")
        ttk.Label(said, wraplength=560, justify="left", padding=(0, 5, 0, 0),
                  text="랜선을 뽑고 Wi-Fi를 끈 뒤 [다시 확인]을 눌러 주세요.\n"
                       "이 프로그램은 네트워크를 쓰지 않지만, 같은 컴퓨터의 다른 프로그램은 "
                       "그렇지 않습니다.").pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(10, 0))
        ttk.Button(row, text="다시 확인", command=self._recheck_gate).pack(side="left")

        # Not a lock. Someone trying the program out has no seed phrase to protect and no
        # reason to unplug their machine, and an override framed as "this is a false
        # positive" would make them claim something untrue to get past it. The check that
        # matters happens when a real seed is about to be searched -- see start_search.
        ttk.Label(box, foreground=self.c["dim"], wraplength=560, justify="left",
                  padding=(0, 8, 0, 0),
                  text="시험 삼아 돌려보는 중이라면 이대로 진행하셔도 됩니다. "
                       "실제 시드 문구를 넣기 직전에 한 번 더 확인합니다."
                  ).pack(anchor="w")

    def _recheck_gate(self):
        self._render_gate()
        self._apply_gate()

    def _apply_gate(self):
        # kept so _render_gate's callers have something to call; the decision moved to
        # start_search, where the seed phrase is actually about to be used
        return

    def _count_words(self, _event=None):
        text = self.mnemonic_text.get("1.0", "end")
        self.word_count.configure(text="{} 단어".format(len(text.split())))
        if getattr(self, "seed_status", None) is None:
            return
        language = (self.config_data or {}).get("wallet", {}).get("language")
        state, message = check_mnemonic(text, language)
        colour = {"ok": self.c["ok"], "bad": self.c["bad"]}.get(state, self.c["muted"])
        self.seed_status.configure(text=message, foreground=colour)
        self.seed_state = state

    # ---- 4. searching ----------------------------------------------------

    def start_search(self):
        mnemonic = " ".join(self.mnemonic_text.get("1.0", "end").split())
        if not mnemonic:
            messagebox.showwarning("시드 문구가 비어 있습니다", "단어를 입력해 주세요.")
            return

        # Asked here rather than enforced earlier. Until this button is pressed there is
        # nothing to protect, and someone testing the program should not have to unplug
        # their machine or claim their network is a false positive. From here on there is
        # a seed phrase in memory, so the question gets asked once, plainly, defaulting to
        # no.
        # Refused, not asked about. A phrase that fails its own checksum is not a judgement
        # call -- it cannot be the phrase that made this wallet, and searching it would burn
        # days to arrive at "not found", which is the one answer guaranteed in advance.
        state, message = check_mnemonic(
            mnemonic, (self.config_data.get("wallet") or {}).get("language"))
        if state == "bad":
            messagebox.showerror(
                "시드 문구를 확인해 주세요", message + "\n\n"
                "이대로는 찾을 수 없습니다. 적어 두신 종이와 한 단어씩 맞춰 보세요.")
            return

        if has_default_route() and not messagebox.askokcancel(
                "네트워크에 연결된 채로 진행합니다",
                "이 컴퓨터는 지금 인터넷에 연결되어 있습니다.\n\n"
                "실제로 쓰던 시드 문구라면 여기서 멈추고 랜선을 뽑거나 Wi-Fi를 끈 뒤 "
                "다시 시작하세요. 이 프로그램은 네트워크를 쓰지 않지만, 같은 컴퓨터의 "
                "다른 프로그램까지 그렇다고 보장할 수는 없습니다.\n\n"
                "시험용 시드 문구이거나 이대로 괜찮다면 [확인]을 누르세요.",
                icon=messagebox.WARNING, default=messagebox.CANCEL):
            return

        self.abort = threading.Event()
        self.result = None
        self.progress_state = (0, self.plan.candidate_count() - self.skip)
        self.started_at = time.monotonic()
        self.show_progress()

        def on_progress(tried, total):
            self.progress_state = (tried, total)     # read by the polling UI thread

        def work():
            result = embed.run(self.plan, mnemonic, progress=on_progress,
                               abort=self.abort, skip=self.skip)
            self.result = result

        threading.Thread(target=work, daemon=True).start()
        self.after(150, self._poll)

    def show_progress(self):
        self._clear()
        self._heading("찾는 중",
                      "이 창을 닫지 마세요. 중단하면 진행 위치가 저장되어 다음에 이어서 할 수 있습니다.")

        # A search runs for hours or days. Someone glancing at the window from across a
        # room needs to see that it is alive and roughly where it is, without reading.
        self.stat_percent = ttk.Label(self.container, text="0.0%", font=self.huge,
                                      foreground=self.c["accent"])
        self.stat_percent.pack(anchor="w")
        self.bar = ttk.Progressbar(self.container, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", pady=(6, 12))

        grid = ttk.Frame(self.container)
        grid.pack(fill="x")
        self.stat_cells = {}
        for column, (key, label) in enumerate((("tried", "확인한 후보"), ("elapsed", "경과"),
                                               ("remaining", "남은 예상"), ("rate", "속도"))):
            cell = ttk.Frame(grid)
            cell.grid(row=0, column=column, sticky="w", padx=(0, 26))
            ttk.Label(cell, text=label, foreground=self.c["dim"], font=self.small
                      ).pack(anchor="w")
            value = ttk.Label(cell, text="—", font=self.bold)
            value.pack(anchor="w")
            self.stat_cells[key] = value

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x")
        self.stop_button = ttk.Button(nav, text="중단", command=self._request_stop)
        self.stop_button.pack(side="right")

    def _request_stop(self):
        self.stop_button.state(["disabled"])
        self.stop_button.configure(text="중단하는 중...")
        self.abort.set()

    def _poll(self):
        tried, total = self.progress_state
        elapsed = time.monotonic() - self.started_at
        rate = tried / elapsed if elapsed > 0 else 0

        share = (tried / total) if total else 0.0
        if total:
            self.bar.configure(value=min(1000, int(1000 * share)))
        self.stat_percent.configure(text="{:.1f}%".format(100.0 * share))
        remaining = (total - tried) / rate if rate > 0 else None
        self.stat_cells["tried"].configure(text="{:,} / {:,}".format(tried, total))
        self.stat_cells["elapsed"].configure(text=humanize(elapsed))
        self.stat_cells["remaining"].configure(text=humanize(remaining))
        self.stat_cells["rate"].configure(text="{:,.0f}개/초".format(rate))

        if self.result is None:
            self.after(200, self._poll)
            return
        self._write_progress(self.skip + self.result.tried)
        self.show_result(self.result)

    # ---- 5. the answer ---------------------------------------------------

    def show_result(self, result):
        self._clear()

        if result.error:
            self._heading("오류", "검색을 시작하지 못했습니다.")
            ttk.Label(self.container, text=result.error, foreground=self.c["bad"],
                      wraplength=640, justify="left").pack(anchor="w")
        elif result.found:
            # This is the thing the whole program exists to say, arrived at after hours or
            # days of a window that looked like it was doing nothing. It should not read
            # like a status line.
            self._clear()
            banner = ttk.Frame(self.container)
            banner.pack(fill="x", pady=(0, 4))
            self._icon(banner, "ok", 40).pack(side="left", padx=(0, 14))
            said = ttk.Frame(banner)
            said.pack(side="left", fill="x", expand=True)
            ttk.Label(said, text="찾았습니다", font=self.huge,
                      foreground=self.c["ok"]).pack(anchor="w")
            ttk.Label(said, foreground=self.c["muted"], font=self.bold,
                      text="{} 만에, 후보 {:,}개를 확인해서 찾았습니다.".format(
                          humanize(result.elapsed),
                          self.skip + result.tried)).pack(anchor="w", pady=(2, 0))
            ttk.Frame(self.container, height=14).pack()

            found = ttk.LabelFrame(self.container, text=" 패스프레이즈 ", padding=14)
            found.pack(fill="x", pady=(0, 12))
            value = tk.Text(found, height=2, wrap="word", font=self.mono, relief="flat")
            value.insert("1.0", result.passphrase)
            value.configure(state="disabled")
            value.pack(fill="x")
            if result.normalization:
                ttk.Label(found, foreground=self.c["muted"], wraplength=600, justify="left",
                          text="유니코드 형태: {}  —  화면으로는 구분되지 않으므로, 다른 지갑에 "
                               "다시 입력할 때 같은 형태로 넣어야 같은 지갑이 열립니다.".format(
                                   result.normalization)).pack(anchor="w", pady=(8, 0))
            # The moment someone is happiest is the moment they are most exposed, and it
            # is the last moment anyone will read anything. Nobody can prove a seed did
            # not leak -- not us, not an auditor. What can be done is make a leak worth
            # nothing, and that is a thing the customer does, in the next few minutes.
            after = ttk.LabelFrame(self.container, text=" 지금 해야 할 일 ", padding=14)
            after.pack(fill="x", pady=(4, 0))
            ttk.Label(after, foreground=self.c["bad"], font=self.bold, wraplength=600,
                      justify="left",
                      text="찾은 즉시 자금을 새 지갑으로 옮기세요.").pack(anchor="w")
            ttk.Label(after, wraplength=600, justify="left", text=(
                "1.  위 패스프레이즈를 종이에 옮겨 적습니다.\n"
                "2.  이 컴퓨터는 계속 오프라인으로 두세요. 다시 연결할 필요가 없습니다.\n"
                "3.  하드웨어 지갑에서 새 지갑을 만들고 받을 주소를 확인합니다.\n"
                "     새 시드 문구는 이 컴퓨터에 절대 입력하지 마세요.\n"
                "4.  찾은 시드 문구와 패스프레이즈로 원래 지갑을 하드웨어 지갑에 복구하고,\n"
                "     하드웨어 지갑과 연동된 휴대폰 앱에서 거래를 만들어 3번 주소로\n"
                "     자금 전부를 한 번에 보냅니다. 서명은 하드웨어 지갑 안에서 이뤄지고,\n"
                "     개인키는 앱으로 전달되지 않습니다.\n"
                "5.  새 시드 문구를 종이에 적어 보관합니다."
            )).pack(anchor="w", pady=(6, 0))

            # The device that broadcasts never sees a private key, so it has nothing to
            # steal. What it can do is show one address and send to another, and the only
            # defence is the hardware wallet's own screen. It is the step people skip.
            ttk.Label(after, foreground=self.c["bad"], font=self.bold, wraplength=600,
                      justify="left",
                      text="보내기 전에 받는 주소를 하드웨어 지갑 화면에서 직접 확인하세요."
                      ).pack(anchor="w", pady=(10, 0))
            ttk.Label(after, wraplength=600, justify="left", text=(
                "앱 화면의 주소와 기기 화면의 주소가 다르면 중단하세요. 거래를 만들어 "
                "네트워크에 올리는 기기는 개인키를 보지 못하므로 훔칠 것이 없지만, "
                "받는 주소를 바꿔치기할 수는 있습니다."
            )).pack(anchor="w", pady=(4, 0))

            # Broadcasting needs a network, so this cannot end offline. What it does not
            # need is *this* machine. And a middle hop through a phone wallet is worse,
            # not better: two fees, and the coins sit under a key held on a networked
            # device in between.
            ttk.Label(after, foreground=self.c["warn"], wraplength=600, justify="left", text=(
                "거래를 네트워크에 올리려면 인터넷에 연결된 기기가 하나 필요하지만, "
                "그것이 이 컴퓨터일 필요는 "
                "없습니다. 하드웨어 지갑을 쓰면 서명이 기기 안에서 끝나므로 시드 문구가 인터넷에 "
                "연결된 기기에 올라가지 않습니다. BIP39 패스프레이즈를 지원하는 기기여야 합니다 "
                "\u2014 Ledger, Trezor, ColdCard 모두 지원합니다. 중간에 다른 지갑을 거치지 "
                "말고 최종 주소로 한 번에 보내세요."
            )).pack(anchor="w", pady=(8, 0))

            # Waiting for hardware to arrive is not free: if the seed did leak, the race is
            # already running. Somewhere imperfect but under their control, today, beats
            # perfect in three days.
            ttk.Label(after, foreground=self.c["dim"], wraplength=600, justify="left", text=(
                "하드웨어 지갑이 없다면 — 주문해서 기다리는 동안에도 위험은 계속됩니다. "
                "본인 명의 거래소 계정이나 새로 설치한 휴대폰 지갑으로 먼저 옮겨 두고, "
                "기기가 도착하면 그때 다시 옮기세요."
            )).pack(anchor="w", pady=(8, 0))
            ttk.Label(after, foreground=self.c["dim"], wraplength=600, justify="left", text=(
                "이 시드 문구와 패스프레이즈는 방금 이 컴퓨터의 메모리를 거쳤습니다. "
                "이 프로그램이 아니더라도 이 컴퓨터에 다른 무엇이 있었는지는 아무도 "
                "증명할 수 없습니다. 자금을 옮기고 나면 옛 시드가 새어 나갔더라도 "
                "빈 지갑이 되므로, 그 증명이 필요 없어집니다."
            )).pack(anchor="w", pady=(8, 0))
        elif result.aborted:
            self._heading("중단했습니다")
            ttk.Label(self.container, wraplength=640, justify="left",
                      text="{:,}개까지 확인했습니다. 진행 위치를 저장했으니 다음에 같은 설정 "
                           "파일로 열면 이어서 할 수 있습니다.".format(self.skip + result.tried)
                      ).pack(anchor="w")
        else:
            self._heading("찾지 못했습니다")
            ttk.Label(self.container, wraplength=640, justify="left",
                      text=self._miss_text()).pack(anchor="w")

        if result.log:
            details = ttk.LabelFrame(self.container, text=" 실행 기록 ", padding=8)
            details.pack(fill="both", expand=True, pady=(12, 0))
            box = tk.Text(details, height=8, wrap="word", font=self.mono)
            box.insert("1.0", self._tidy_log(result.log) or "(없음)")
            box.configure(state="disabled")
            box.pack(fill="both", expand=True)

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(nav, text="처음으로", command=self.show_checks).pack(side="left")
        ttk.Button(nav, text="닫기", command=self.destroy).pack(side="right")


    # Lines btcrecover writes for someone at a command line. In a window they are advice
    # nobody can take -- there is no flag to add -- and they sit between the two lines that
    # do matter: which backend was chosen, and whether a seed word was substituted.
    LOG_NOISE = (
        "Use --skip-pre-start to skip",
        "This can be overridden with --mnemonic-length",
        "Add --no-dupchecks up to 4 times",
        "Wallet Type: btcrpass.",
    )

    @classmethod
    def _tidy_log(cls, log):
        kept = []
        for line in (log or "").splitlines():
            if any(noise in line for noise in cls.LOG_NOISE):
                continue
            kept.append(line)
        return "\n".join(kept).strip()

    def _miss_text(self):
        """What "not found" means, which is different when only a part was searched.

        Someone running a seventh of the work will read a plain "not found" as "the
        passphrase is not in this range" and stop. That is the wrong conclusion and the
        expensive one -- the answer may be sitting in a part another machine has not
        finished yet.
        """
        plan = self.plan
        if plan.of > 1:
            return ("{}번째 구간 {:,}개를 모두 확인했지만 이 구간에는 없었습니다.\n\n"
                    "이것은 전체 {:,}개 중 일부입니다. 패스프레이즈가 설정한 범위 밖이라는 "
                    "뜻이 아니므로, 나머지 구간을 돌리는 다른 컴퓨터의 결과를 확인해 주세요."
                    .format(plan.part, plan.candidate_count(), plan.total_count()))
        return ("설정된 {:,}개 후보를 모두 확인했지만 일치하는 것이 없었습니다.\n\n"
                "시드 문구를 잘못 입력했거나, 실제 패스프레이즈가 이 조합 범위 밖에 "
                "있습니다. 기억나는 조각을 다시 정리해 새 설정 파일을 받아 보세요."
                .format(plan.candidate_count()))


def self_test_from_terminal(report_path=None):
    """Run the self-test with no window, and say plainly whether it passed.

    A built executable can be checked this way without clicking anything -- by whoever
    built it, by a CI job, and by whoever downloaded it and wants to see it work before
    it is shown a seed phrase.

    A windowed build on Windows has no stdout at all, so the exit code carries the
    verdict and `report_path` is how a build job reads the detail. That way the binary
    that gets tested is the same one that gets shipped.
    """
    from btcrecover import crypto_backends
    # Named explicitly because the fallback announces itself with a warning on stderr at
    # import time -- long before anything here could capture it. A build that quietly
    # shipped the pure-Python backend would otherwise pass this test and crawl in the field.
    lines = ["자가검증: 공개 BIP39 테스트 벡터로 알려진 패스프레이즈를 찾습니다.",
             "secp256k1 backend: " + crypto_backends.BACKEND_NAME]
    try:
        plan = embed.SearchPlan(SELF_TEST["config"])
        result = embed.run(plan, SELF_TEST["mnemonic"])
    except Exception as e:
        result, plan = embed.SearchResult(error=str(e)), None
    if result.found and result.passphrase == SELF_TEST["passphrase"]:
        code = 0
        lines.append("통과 — '{}' 을 {:,}개 중 {}번째에서 {:.2f}초 만에 찾았습니다.".format(
            result.passphrase, plan.candidate_count(), result.tried + 1, result.elapsed))
    else:
        code = 1
        lines.append("실패 — " + (result.error or "정답을 찾지 못했습니다"))
    if result.log:
        lines.append("")
        lines.append(result.log.strip())

    # Write the record before printing it. Printing is the part that can fail -- a console
    # that cannot encode Hangul takes the whole verdict with it otherwise, which is how
    # this was found.
    if report_path:
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            print("보고 파일을 쓸 수 없습니다:", e)
            return 1
    for line in lines[:3]:
        print(line)

    # Leave with exactly the code we decided on. The search leaves worker processes and a
    # pool behind, and anything that goes wrong while the interpreter tears those down
    # would otherwise overwrite the verdict -- a passing self-test reported as a failure.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)


USAGE = """사용법: passphrase-recovery [옵션]

옵션 없이 실행하면 복구 창이 열립니다.

  --self-test        공개 BIP39 테스트 벡터로 알려진 패스프레이즈를 찾아, 프로그램이
                     제대로 동작하는지 확인합니다. 통과하면 0, 실패하면 0이 아닌 값으로
                     종료합니다.
  --report FILE      자가검증 결과를 파일로 기록합니다. 창만 있는 Windows 빌드는 출력할
                     콘솔이 없으므로, 그런 빌드에서는 이 파일이 유일한 상세 기록입니다.
  -h, --help         이 도움말을 출력합니다.

Windows 에서 --self-test 를 셸에서 실행하면 프롬프트가 곧바로 돌아옵니다. 셸이 창 있는
프로그램을 기다리지 않기 때문이며, 고장이 아닙니다. --report 로 지정한 파일이 생기기를
기다리거나, 창의 첫 화면에 있는 자가검증 버튼을 쓰세요."""


def main():
    embed.prepare_frozen_start()   # must come first; see btcrecover/embed.py
    argv = sys.argv[1:]
    # Answer --help without opening anything. run-all-tests.py runs every script in the
    # repository this way and accepts only a clean exit; falling through to the window
    # instead means a headless machine fails and a desktop one hangs holding it open.
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        sys.exit(0)
    if "--self-test" in argv:
        report = None
        if "--report" in argv:
            index = argv.index("--report") + 1
            if index >= len(argv):
                sys.exit("--report needs a file path")
            report = argv[index]
        sys.exit(self_test_from_terminal(report))
    RecoveryApp().mainloop()


if __name__ == "__main__":
    main()
