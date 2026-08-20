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

import hashlib, json, os, queue, socket, sys, threading, time, tkinter as tk
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


def fingerprint(config):
    """Identifies a config, so a resume file cannot be applied to a different search."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def humanize(seconds):
    if seconds is None or seconds != seconds or seconds == float("inf"):
        return "계산 중"
    seconds = int(seconds)
    if seconds < 60:      return "{}초".format(seconds)
    if seconds < 3600:    return "{}분".format(seconds // 60)
    if seconds < 172800:  return "{:.1f}시간".format(seconds / 3600)
    if seconds < 63072000: return "{:.1f}일".format(seconds / 86400)
    return "{:,}년".format(int(seconds / 31557600))


class RecoveryApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("패스프레이즈 복구")
        self.geometry("720x560")
        self.minsize(640, 520)

        self._install_fonts()
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

    def _install_fonts(self):
        families = set(tkfont.families())
        for name in ("Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", "NanumGothic"):
            if name in families:
                for style in ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont"):
                    tkfont.nametofont(style).configure(family=name)
                break
        tkfont.nametofont("TkDefaultFont").configure(size=11)
        self.title_font = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        self.title_font.configure(size=16, weight="bold")
        self.mono = tkfont.Font(family="Consolas" if "Consolas" in families else "Courier", size=13)

    # ---- screen plumbing -------------------------------------------------

    def _clear(self):
        for child in self.container.winfo_children():
            child.destroy()

    def _heading(self, text, subtitle=None):
        ttk.Label(self.container, text=text, font=self.title_font).pack(anchor="w")
        if subtitle:
            ttk.Label(self.container, text=subtitle, foreground="#555",
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
            ttk.Label(box, foreground="#b45309", wraplength=620, justify="left",
                      text="이 컴퓨터는 아직 네트워크에 연결되어 있습니다.\n"
                           "랜선을 뽑고 Wi-Fi를 끈 뒤 [다시 확인]을 눌러 주세요. "
                           "이 프로그램은 네트워크를 쓰지 않지만, 같은 컴퓨터의 다른 프로그램은 "
                           "그렇지 않을 수 있습니다.").pack(anchor="w")
            ttk.Button(box, text="다시 확인", command=self.show_checks).pack(anchor="w", pady=(8, 0))
        else:
            ttk.Label(box, foreground="#15803d",
                      text="네트워크에 연결되어 있지 않습니다. 좋습니다.").pack(anchor="w")

        box2 = ttk.LabelFrame(self.container, text=" 2. 동작 자가검증 ", padding=12)
        box2.pack(fill="x", pady=(0, 12))
        ttk.Label(box2, wraplength=620, justify="left",
                  text="공개된 BIP39 테스트 벡터로 프로그램이 제대로 계산하는지 확인합니다.\n"
                       "본인의 시드 문구를 넣기 전에 먼저 돌려 보세요. 이 검증에는 본인 정보가 "
                       "전혀 쓰이지 않습니다.").pack(anchor="w")
        self.selftest_label = ttk.Label(box2, text="", foreground="#555")
        self.selftest_label.pack(anchor="w", pady=(8, 0))
        self.selftest_button = ttk.Button(box2, text="자가검증 실행", command=self.run_self_test)
        self.selftest_button.pack(anchor="w", pady=(8, 0))

        ttk.Label(self.container, foreground="#666", wraplength=640, justify="left",
                  text="이 프로그램은 어떤 네트워크 요청도 하지 않습니다. 위의 연결 확인은 "
                       "패킷을 보내지 않고 운영체제의 경로표만 읽습니다.").pack(anchor="w", pady=(4, 12))

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x")
        ttk.Button(nav, text="설정 파일 열기  →", command=self.load_config).pack(side="right")

    def run_self_test(self):
        self.selftest_button.state(["disabled"])
        self.selftest_label.configure(text="실행 중...", foreground="#555")
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
                text="통과 — 알려진 정답 '{}' 을 {:.1f}초 만에 찾았습니다.".format(
                    result.passphrase, result.elapsed), foreground="#15803d")
        else:
            self.selftest_label.configure(
                text="실패 — " + (result.error or "정답을 찾지 못했습니다") +
                     "\n이 상태로는 본인 시드를 넣지 마세요.", foreground="#b91c1c")

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
            ("시도할 패스프레이즈", "{:,}개".format(total)),
            ("유니코드 정규화", ", ".join(plan.normalizations)),
        ]
        if self.skip:
            rows.append(("이어서 시작", "{:,}번째부터 (남은 {:,}개)".format(self.skip, total - self.skip)))
        for i, (label, value) in enumerate(rows):
            ttk.Label(grid, text=label, foreground="#666").grid(row=i, column=0, sticky="nw", pady=3)
            ttk.Label(grid, text=value, wraplength=460, justify="left").grid(
                row=i, column=1, sticky="w", padx=(16, 0), pady=3)

        if len(plan.normalizations) > 1:
            ttk.Label(self.container, foreground="#b45309", wraplength=640, justify="left",
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

        self.word_count = ttk.Label(self.container, text="0 단어", foreground="#666")
        self.word_count.pack(anchor="w")
        self.mnemonic_text.bind("<KeyRelease>", self._count_words)

        ttk.Label(self.container, foreground="#b45309", wraplength=640, justify="left",
                  text="복구에 성공하면 자금을 곧바로 새 지갑으로 옮기세요. 이 시드 문구는 "
                       "복구 과정에서 메모리에 올라왔으므로 더 이상 안전하다고 볼 수 없습니다."
                  ).pack(anchor="w", pady=(12, 0))

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x")
        ttk.Button(nav, text="←  뒤로", command=self.show_summary).pack(side="left")
        ttk.Button(nav, text="찾기 시작", command=self.start_search).pack(side="right")

    def _count_words(self, _event=None):
        words = self.mnemonic_text.get("1.0", "end").split()
        self.word_count.configure(text="{} 단어".format(len(words)))

    # ---- 4. searching ----------------------------------------------------

    def start_search(self):
        mnemonic = " ".join(self.mnemonic_text.get("1.0", "end").split())
        if not mnemonic:
            messagebox.showwarning("시드 문구가 비어 있습니다", "단어를 입력해 주세요.")
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

        self.bar = ttk.Progressbar(self.container, mode="determinate", maximum=1000)
        self.bar.pack(fill="x", pady=(0, 10))
        self.stat_tried = ttk.Label(self.container, text="", font=self.mono)
        self.stat_tried.pack(anchor="w")
        self.stat_rate = ttk.Label(self.container, text="", foreground="#666")
        self.stat_rate.pack(anchor="w", pady=(4, 0))

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

        if total:
            self.bar.configure(value=min(1000, int(1000 * tried / total)))
        self.stat_tried.configure(text="{:,} / {:,}   ({:.1f}%)".format(
            tried, total, 100.0 * tried / total if total else 0.0))
        remaining = (total - tried) / rate if rate > 0 else None
        self.stat_rate.configure(text="{:,.0f}개/초   경과 {}   남은 예상 {}".format(
            rate, humanize(elapsed), humanize(remaining)))

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
            ttk.Label(self.container, text=result.error, foreground="#b91c1c",
                      wraplength=640, justify="left").pack(anchor="w")
        elif result.found:
            self._heading("찾았습니다")
            found = ttk.LabelFrame(self.container, text=" 패스프레이즈 ", padding=14)
            found.pack(fill="x", pady=(0, 12))
            value = tk.Text(found, height=2, wrap="word", font=self.mono, relief="flat")
            value.insert("1.0", result.passphrase)
            value.configure(state="disabled")
            value.pack(fill="x")
            if result.normalization:
                ttk.Label(found, foreground="#666", wraplength=600, justify="left",
                          text="유니코드 형태: {}  —  화면으로는 구분되지 않으므로, 다른 지갑에 "
                               "다시 입력할 때 같은 형태로 넣어야 같은 지갑이 열립니다.".format(
                                   result.normalization)).pack(anchor="w", pady=(8, 0))
            ttk.Label(self.container, foreground="#b91c1c", wraplength=640, justify="left",
                      text="지금 바로 자금을 새로 만든 지갑으로 옮기세요. 이 시드 문구와 "
                           "패스프레이즈는 이 컴퓨터의 메모리를 거쳤습니다.").pack(anchor="w")
        elif result.aborted:
            self._heading("중단했습니다")
            ttk.Label(self.container, wraplength=640, justify="left",
                      text="{:,}개까지 확인했습니다. 진행 위치를 저장했으니 다음에 같은 설정 "
                           "파일로 열면 이어서 할 수 있습니다.".format(self.skip + result.tried)
                      ).pack(anchor="w")
        else:
            self._heading("찾지 못했습니다")
            ttk.Label(self.container, wraplength=640, justify="left",
                      text="설정된 {:,}개 후보를 모두 확인했지만 일치하는 것이 없었습니다.\n\n"
                           "시드 문구를 잘못 입력했거나, 실제 패스프레이즈가 이 조합 범위 밖에 "
                           "있습니다. 기억나는 조각을 다시 정리해 새 설정 파일을 받아 보세요."
                           .format(self.plan.candidate_count())).pack(anchor="w")

        if result.log:
            details = ttk.LabelFrame(self.container, text=" 실행 기록 ", padding=8)
            details.pack(fill="both", expand=True, pady=(12, 0))
            box = tk.Text(details, height=8, wrap="word", font=self.mono)
            box.insert("1.0", result.log.strip() or "(없음)")
            box.configure(state="disabled")
            box.pack(fill="both", expand=True)

        nav = ttk.Frame(self.container)
        nav.pack(side="bottom", fill="x", pady=(12, 0))
        ttk.Button(nav, text="처음으로", command=self.show_checks).pack(side="left")
        ttk.Button(nav, text="닫기", command=self.destroy).pack(side="right")


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

    for line in lines[:3]:
        print(line)
    if report_path:
        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            print("보고 파일을 쓸 수 없습니다:", e)
            return 1
    return code


def main():
    embed.prepare_frozen_start()   # must come first; see btcrecover/embed.py
    argv = sys.argv[1:]
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
