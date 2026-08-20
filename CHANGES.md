# Changes in this fork

This repository is a fork of [3rdIteration/btcrecover](https://github.com/3rdIteration/btcrecover),
maintained by Stephen Rothery, which is itself a continuation of the original *btcrecover* by
Christopher Gurnee. All of their work remains under their copyright.

Like the upstream project, this fork is distributed under the **GNU General Public License, version 2
or (at your option) any later version** — see [LICENSE.txt](LICENSE.txt). That means anyone who
receives this software, in source or binary form, is free to read it, modify it, and redistribute it,
and is entitled to the complete corresponding source code.

GPLv2 section 2(a) requires modified files to carry a notice of the change and its date. Each file
changed here carries such a notice in its header, and the changes are summarized below.

The first commit in this repository is an unmodified snapshot of upstream, so everything this fork
changed is exactly `git diff <that commit> HEAD` — no summary here can drift away from the code.

---

## 2026-08-20 — The Windows build works

Verified on `windows-latest`, from a commit, on a public runner: dependencies, the four
suites covering this fork, a PyInstaller build in 22 seconds, and the built program
recovering the published BIP39 test vector in 0.86 seconds on the coincurve backend.
19.7 MB packaged, three minutes end to end.

Five failures got there, and they are worth keeping in view because only the third was
a mistake in the program rather than in how it was being checked:

1. `coincurve.__version__`, which coincurve does not define — a check that could only fail.
2. Upstream's own test suites, on a platform upstream does not test. Still running after
   twenty-two minutes, leaking file handles that Windows will not let go of.
3. **A real bug.** A Windows console encodes as cp1252, where Hangul does not exist, so
   the program died printing its own first line. The same crash would have hit a recovered
   Korean seed phrase at the moment of success.
4. and 5. A shell does not wait for a GUI-subsystem executable. Both runs checked the exit
   code and the report before the program had produced either. Two guesses at the cause
   were wrong; making the step report what it saw found it on the first try.

The program had been working on Windows since (3) was fixed. The last two failures were
the harness misreading it.

**Changed:** `recovery_gui.py`, `.gitignore`
**Added:** `recovery_gui.spec`, `.github/workflows/build-windows.yml`

A PyInstaller folder build, and a Windows build job that tests what it ships.

`recovery_gui.py --self-test [--report FILE]` recovers a known passphrase and exits
non-zero if it cannot. A windowed Windows build has no stdout, so the exit code carries the
verdict and the report file carries the detail — which means CI can check the same binary it
publishes, not a console-mode stand-in. It is equally useful to whoever downloaded the
program and wants to watch it work before showing it a seed phrase.

Building locally first turned up two failures that would have shipped:

* `wallycore` reaches its native library through `importlib.import_module("_wallycore")`,
  invisible to static analysis. Without it the build still runs and still passes its
  self-test, on the pure-Python secp256k1 — about two orders of magnitude slower, announced
  only by a warning. The build job now fails if that warning appears.
* `bitcoinlib` reads `config/VERSION` and `data/` at import time and will not load without
  them.

The build is a folder rather than one file, and UPX is off. A one-file build unpacks to a
temporary directory at each launch, which is the shape antivirus heuristics like least and
the shape that hides what shipped; a folder can be read and diffed.

Verified on the frozen binary: workers peak at one parent plus fourteen, exactly the
expected count, so `prepare_frozen_start()` does hold.

---

## 2026-08-20 — The offline recovery window

**Changed:** `btcrecover/embed.py`
**Added:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`

A tkinter window with four screens: check, load the config, type the seed phrase, watch it
run. Chosen over a heavier toolkit because this is a program strangers are asked to trust —
a small bundle with few dependencies is a smaller surface to explain and to reproduce.

The seed phrase is typed in the window and held only in memory. The resume file records a
candidate count and a fingerprint of the config, so a saved position cannot be applied to a
different search, and holds nothing else. Tests assert that.

Before any of it, the first screen reports whether the machine still has a network route --
read from the local routing table with no packet sent -- and offers a self-test that
recovers a known passphrase from the published BIP39 test vector, so an owner can watch the
program work before trusting it with their own seed.

Two problems found while building it:

* Tkinter allows one `Tk()` per process; a second one segfaults on macOS instead of raising.
  btcrseed creates its own root when it needs to prompt, so `embed.run` now lends it the
  host's. A SearchPlan supplies everything btcrseed would ask for, so this should be
  unreachable -- but a segfault there would take a running recovery with it.
* The self-test called `after()` from its worker thread, which tkinter does not allow. It
  polls from the main thread now, as the search already did.

---

## 2026-08-20 — Running a search from inside an application

**Changed:** `btcrecover/btcrpass.py`
**Added:** `btcrecover/embed.py`, `btcrecover/test/test_embed.py`

`btcrpass.main()` assumes a terminal: it prints, and it reports bad input by calling
`sys.exit`. Two hooks make it embeddable without disturbing that — `progress_hook(tried,
total)` fires as the search advances and once more when it stops, and `abort_event` is
polled between chunks so a stop button leaves nothing half-checked. Both default to unset,
and the command line behaves exactly as before.

`btcrecover.embed` wraps them. It builds the argv from a config.json, hands the grammar to
btcrpass as its `base_iterator` so no candidate reaches a pipe or a file, and returns a
`SearchResult` rather than exiting. The mnemonic is a parameter and never comes from the
config.

`WalletBIP39.normalization_of()` re-derives which Unicode form matched. The worker process
that found the match printed the form to its own stdout, which an embedding host never
sees; asking again costs at most four PBKDF2 rounds.

Two hazards found while building this, both of which would have surfaced first as a broken
executable:

* A host whose module-level code is not behind `if __name__ == "__main__"` fills the machine
  with processes within seconds, because each spawned worker re-runs the program. This is
  reproducible in a plain script, not only in a frozen build.
* A windowed PyInstaller build leaves `sys.stdout` as `None`. BTCRecover prints from its
  workers at the moment a match is found, so success would be the one outcome that crashes.
  `embed.prepare_frozen_start()` handles both, and must be the first thing a frozen entry
  point does.

---

## 2026-08-20 — Priority ordering for grammar candidates

**Changed:** `btcrecover/passphrase_grammar.py`, `webapp/diagnostic.html`

Candidates are now emitted in likelihood order rather than odometer order. Each slot splits
its values into tiers, a candidate's cost is the sum of its slots' tier numbers, and blocks
are emitted cheapest first. The model itself is currently a single rule — a four-digit run
is tried as a year (1900–2099) before anything else — kept small and contiguous so it can be
replaced by real case statistics without changing the machinery.

Measured rank of the correct passphrase in a 20,000-candidate grammar: 2,025 → 125 for
`비밀번호2024`, and 11,999 → 299 when the answer used the second of two words. A four-digit
run that is *not* a year loses about 200 places, which is the bounded cost of the same
choice.

Ordering changes only the order: the candidate set, and so `count()` and the quoted ETA, are
identical either way, and the tests assert it. `"priority": false` restores the raw product
order.

This also made resumption strictly better. A tier fixes whether each slot is empty, so every
candidate in a block costs the same to count past, and `--skip` is a division even when the
grammar has optional slots — where it previously had to walk. Skipping 200 million candidates
into a 222-million-candidate space is now immediate.

---

## 2026-08-20 — Passphrase grammars, and normalization on the passphrase-search path

**Changed:** `btcrecover/btcrpass.py`
**Added:** `btcrecover/passphrase_grammar.py`, `btcrecover/test/test_passphrase_grammar.py`,
`docs/Passphrase_Grammar.md`, `webapp/diagnostic.html`

`btcrpass.WalletBIP39` searches the passphrase itself with the mnemonic held fixed, which
is the path that matters when the mnemonic is already known. It normalized every candidate
to NFKD, so it had the same blind spot as the seed-search path fixed above, and the fix had
to be made twice. Both the CPU and OpenCL paths now try each requested form, and
`--passphrase-normalizations` is available on `btcrecover.py` as well as `seedrecover.py`.

`btcrecover.passphrase_grammar` expands a small JSON description of a passphrase -- some
remembered words, a digit range, an optional symbol -- into candidates on demand. Slots are
indexed rather than materialized, so a slot covering every digit string up to eight
characters is 111,111,110 candidates that cost nothing to construct, and the output is a
stream that pipes into `--passwordlist -`. The order is fixed and `--skip` resumes into it,
by division rather than by walking where no slot is optional.

`webapp/diagnostic.html` is a self-contained page that builds such a grammar from what a
user remembers and reports how large the search is, how long it would take, and which
remembered detail would shrink it most. It makes no network request; the grammar is
assembled in the browser and downloaded from a Blob.

Both implementations count candidates with the same formula, and the tests pin them to each
other. An optional slot that goes empty drops the separator that would have followed it, so
the count is not the plain product of the slot sizes.

Worth knowing when choosing a path: with one known mnemonic, `seedrecover.py
--passphrase-list` has a single unit of work and so uses one core no matter how many
workers it reports, and holds every passphrase in memory. Measured over 20,000 candidates,
`btcrecover.py --wallet-type bip39 --passwordlist -` finished the same search in 2.3s at
918% CPU against 17.2s at 100%.

---

## 2026-08-20 — Unicode normalization for non-ASCII BIP39 passphrases

**Changed:** `btcrecover/btcrseed.py`
**Added:** `btcrecover/test/test_cjk_passphrase.py`, `docs/CJK_Passphrase_Normalization.md`

BIP39 specifies that the passphrase is NFKD-normalized before it is used as the PBKDF2 salt, and
upstream implements exactly that. Some wallets never normalized what the user typed, however, and
hashed it as-is. For an ASCII passphrase this is indistinguishable; for Hangul, Kana, and other
scripts with composed and decomposed representations it is a different byte string, and therefore a
different seed and a different wallet. Such a wallet could not be recovered by upstream even when
both the mnemonic and the passphrase were exactly correct.

* New `--passphrase-normalizations` option, taking a comma-separated list of forms
  (`NFKD`, `NFC`, `NFD`, `NFKC`) or `all`. The default remains `NFKD`, so existing behaviour and the
  BIP39 spec are preserved unless the option is given.
* `WalletBIP39.config_mnemonic()` now derives one salt per *distinct* normalization form. Duplicates
  are dropped, so an ASCII passphrase still produces exactly one salt regardless of the forms
  requested, and Hangul produces two rather than four.
* Matches report which form they came from (`… Passphrase: 비밀번호2024 [NFC]`). NFC and NFD are
  indistinguishable on screen, and the recovered passphrase must be re-entered in the same form for
  the destination wallet to derive the same seed.
* `WalletAezeed` clears the form labels it inherits from `WalletBIP39.config_mnemonic()`, since it
  salts the passphrase verbatim and would otherwise misreport which normalization matched.

Electrum 2.x is unaffected: it defines and consistently applies its own normalization.

### Verification

`btcrecover/test/test_cjk_passphrase.py` contains a ground-truth generator that rebuilds the expected
addresses from the BIP39 and BIP32 specifications without importing btcrecover, anchored against the
published BIP39 test vector — so a bug in the normalization under test cannot mask itself.

```bash
python -m unittest btcrecover.test.test_cjk_passphrase
python -m unittest btcrecover.test.test_seeds
python -m unittest btcrecover.test.test_passwords
```

Note that `test_seeds` and `test_passwords` share global state and must be run in separate processes,
as `run-all-tests.py` does; this is pre-existing upstream behaviour.
