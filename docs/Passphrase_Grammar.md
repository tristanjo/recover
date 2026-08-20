# Passphrase Grammars

When the mnemonic is known and the passphrase is not, the search space is whatever the
owner can still remember about it: a couple of words, roughly how many digits followed,
maybe a symbol. A **grammar** describes that space in a few hundred bytes and expands it
into candidates on demand.

`webapp/diagnostic.html` writes these grammars; `btcrecover.passphrase_grammar` expands
them. Both count candidates the same way, so the estimate the owner is shown is the
search that actually runs.

## Use the passphrase-search path, not the seed-search path

This matters more than anything else on this page.

```bash
python -m btcrecover.passphrase_grammar config.json | python btcrecover.py \
    --wallet-type bip39 --language en \
    --mnemonic "abandon abandon ... about" \
    --addrs 12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu --addr-limit 5 \
    --bip32-path "m/44'/0'/0'/0" \
    --passwordlist - --passphrase-normalizations all
```

`seedrecover.py --passphrase-list` also works, but it searches *mnemonics* and treats
passphrases as a multiplier applied inside each one. With a single known mnemonic there
is exactly one unit of work, so however many worker threads it reports, only one of them
has anything to do, and every passphrase must be held in memory at once.

Measured on a 14-core machine, 20,000 passphrases against the same wallet:

| | wall clock | CPU | memory |
|---|---|---|---|
| `seedrecover.py --passphrase-list` | 17.2 s | 100% (1 core busy) | whole list resident |
| `btcrecover.py --passwordlist -` | 2.3 s | 918% | streamed |

`btcrecover.py --wallet-type bip39` searches the passphrase itself, so it gets the worker
pool, streaming input, `--skip`, autosave, and the progress bar that the rest of
BTCRecover already has.

## The grammar

```json
{
  "passphrase": {
    "slots": [
      {"type": "words",  "candidates": ["비밀번호", "우리집"], "cases": ["asis", "title"]},
      {"type": "digits", "length": [2, 4]},
      {"type": "symbols", "candidates": ["!", "@"], "optional": true}
    ],
    "separators": ["", "-"],
    "permute_order": false,
    "normalizations": ["NFKD", "NFC"]
  }
}
```

**Slots**, joined in order:

| type | takes | notes |
|---|---|---|
| `words` | `candidates`, `cases` | `cases` from `asis`, `lower`, `title`, `upper`; forms that collide are counted once |
| `digits` | `length: [min, max]` **or** `candidates` | a range covers every string of those lengths, leading zeros kept (`0301` ≠ `301`); a range including length 4 tries years first |
| `symbols` | `candidates` | |
| `fixed` | `candidates` | for a part that is remembered exactly |

Any slot may be `optional`, meaning it might not have been there at all.

**`separators`** are the strings that may join adjacent parts — every combination is
tried. **`permute_order`** tries every ordering of the parts, and multiplies the search
by the factorial of the part count; leave it off whenever the order is remembered.

**`normalizations`** is passed to `--passphrase-normalizations`; see
[Non-ASCII (CJK) BIP39 Passphrases](CJK_Passphrase_Normalization.md).

### An empty slot takes its separator with it

An optional slot that goes empty drops out along with the separator that would have
followed it, so `a`, absent `b`, `c` joined by `-` gives `a-c` rather than `a--c`. A
candidate built from a single part has nowhere to put a separator and is emitted once,
not once per separator.

This is why the candidate count is not the plain product of the slot sizes, and why
`count()` sums over each subset of optional slots that could go empty.

## Priority order

Candidates are emitted in likelihood order by default. Right now that model is one rule:
**a four-digit run is tried as a year (1900–2099) before it is tried as anything else.**
Birth years, wedding years, the year someone bought their first coin — these are what
four digits in a passphrase usually are.

Measured rank of the correct passphrase, same grammar either way:

| what the digits were | plain order | priority order | |
|---|---|---|---|
| `비밀번호2024` (2 words × 4 digits) | 2,025 | 125 | 16x sooner |
| `우리집1998` (second word) | 11,999 | 299 | 40x sooner |
| `minji1988` | 1,989 | 89 | 22x sooner |
| `minji0301` (a date, not a year) | 302 | 502 | 0.6x — *slower* |

The last row is the honest cost: pushing 200 years to the front pushes everything else
back by 200. That penalty is bounded and small; the gain is up to a factor of thousands.

When slots disagree, cost is the **sum of tier numbers** — a candidate settling for a
second choice in one slot is tried before one settling for second choices in two.

Set `"priority": false` in the grammar to get the raw product order instead. Either way
the *set* of candidates is identical, so `count()` and the ETA are unchanged: ordering
only decides how early within that total a search is likely to stop.

### Replacing the model

`YEAR_RANGE` in `btcrecover/passphrase_grammar.py` is deliberately the whole of it — a
small prior that can be stated and defended, sitting where statistics from real cases
belong. Whatever replaces it must stay expressible as **index ranges** over a slot's
values. That is what keeps a tier free to construct when it covers ten million values,
and what keeps `--skip` a division rather than a walk.

## Command line

```bash
python -m btcrecover.passphrase_grammar config.json --count   # how many candidates
python -m btcrecover.passphrase_grammar config.json --limit 20   # peek at the order
python -m btcrecover.passphrase_grammar config.json --skip 4000000   # resume
```

Candidates come out in a fixed order, so `--skip` resumes exactly where a previous run
stopped. In priority order the skip is always a division rather than a walk — a tier fixes
whether each slot is empty, so every candidate within one block costs the same to count
past. Skipping 200 million candidates into a 222-million-candidate space is immediate.

Slots are indexed rather than materialized: a slot covering every digit string up to
eight characters is 111,111,110 candidates and costs nothing to construct.

## Running a search from an application

`btcrecover.embed` runs the same search in-process, for a GUI rather than a terminal.
The grammar goes to btcrpass as its `base_iterator`, so no candidate is ever written to
a pipe or a file.

```python
from btcrecover import embed

plan = embed.SearchPlan.from_file("config.json")
result = embed.run(plan, mnemonic, progress=on_progress, abort=stop_event)
if result.found:
    show(result.passphrase, result.normalization)
elif result.aborted:
    remember(result.tried)        # pass back as `skip` to resume
elif result.error:
    show_error(result.error)
```

The mnemonic is a parameter and never comes from the config — the config is written on a
website, and a seed phrase must not be.

`progress(tried, total)` is called from the search thread, including once when the search
stops, so a progress bar lands where the search ended. `abort` is a `threading.Event`;
setting it stops between chunks, leaving nothing half-checked. Bad input that would make
the command line call `sys.exit` comes back as `result.error` instead.

`result.normalization` is re-derived in the calling process. The worker that found the
match printed the form to its own stdout, which the host never sees.

### Two things a host must do

**Guard your module-level code.** `if __name__ == "__main__":` around everything that
runs at import. Worker processes start by re-importing the entry module, and without the
guard each one re-runs the program and starts its own workers. This fills a machine with
processes in seconds — it is not a slow leak.

**Call `embed.prepare_frozen_start()` first** in a frozen executable, before any other
work. It installs `multiprocessing.freeze_support()`, which is what stops the same
runaway when there is no `__main__` guard to reach, and it gives `print()` somewhere to
go: a windowed PyInstaller build leaves `sys.stdout` as `None`, and BTCRecover prints
from its workers at the moment a match is found — so without it, success is the one
outcome that crashes.

## The recovery window

`recovery_gui.py` is the offline program a wallet owner actually runs. Four screens:
check, load the config, type the seed phrase, watch it run.

```bash
python recovery_gui.py
```

The seed phrase is typed there and nowhere else. It is not in the config, which was
written on a website, and it is not in the resume file, which holds a candidate count and
a fingerprint of the config so a position cannot be applied to a different search.

The first screen does two things before any of that. It reports whether the machine still
has a network route — read from the local routing table, no packet sent — and it offers a
**self-test**: recovering a known passphrase from the published BIP39 test vector, so
someone can watch the program work, and watch their network monitor stay silent, before
trusting it with their own seed phrase.

Stopping is safe: the search halts between chunks and the position is saved, so reopening
the same config offers to continue.

### One Tk root per process

Tkinter allows exactly one `Tk()` per process; creating a second after destroying the
first segfaults on macOS rather than raising. btcrseed builds its own root when it needs
to prompt for something, so `embed.run` lends it the host's root instead. A `SearchPlan`
supplies everything btcrseed would prompt for, which makes that unreachable — but the
crash it would cause takes a running recovery with it.

The same rule governs testing: `btcrecover/test/test_recovery_gui.py` shares a single
window across every test rather than opening one per test.

## Building the program

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean recovery_gui.spec
dist/passphrase-recovery/passphrase-recovery --self-test
```

A **folder**, not a single file. A one-file build unpacks itself to a temporary directory
at every launch, which is both the shape antivirus heuristics dislike most and the shape
that hides what shipped. A folder can be looked through, and diffed against a build made
from the same source. UPX packing is off for the same reason.

`--self-test` runs the recovery of a known passphrase and exits non-zero if it fails. A
windowed Windows build has no stdout, so the exit code carries the verdict and
`--report FILE` carries the detail — which is how CI checks *the binary it is about to
ship*, rather than a console-mode stand-in.

### Running --self-test on Windows

A shell does not wait for a GUI-subsystem executable. Typing

```
passphrase-recovery.exe --self-test --report self-test.txt
```

into `cmd` returns the prompt immediately, prints nothing, and leaves `%ERRORLEVEL%`
meaningless — while the program is still running behind it. Nothing is wrong; the shell
simply moved on. Read `self-test.txt` once it appears, or wait for it explicitly:

```powershell
$p = Start-Process .\passphrase-recovery.exe -ArgumentList "--self-test","--report","self-test.txt" `
       -NoNewWindow -Wait -PassThru
$p.ExitCode
```

For anyone not at a terminal, the window's first screen has a self-test button, which is
the same check with the result on screen.

### Two things the spec exists to fix

`wallycore` reaches its native library through `importlib.import_module("_wallycore")`,
which PyInstaller's static analysis cannot see. Miss it and the build still works, still
passes its self-test, and runs on the pure-Python secp256k1 — roughly two orders of
magnitude slower, with only a warning to say so. The build job greps for that warning.

`bitcoinlib` reads `config/VERSION` and its `data/` directory at import time and refuses
to load without them. Both are listed as `datas`, along with the BIP39 wordlists that
btcrseed locates relative to its own `__file__`.

### The Windows build

`.github/workflows/build-windows.yml` builds on a tag, on a public runner, from a commit.
It runs the test suite, self-tests the built program, publishes the SHA256 into the run
log where it cannot be edited afterwards, and records a provenance attestation:

```bash
gh attestation verify passphrase-recovery-*.zip --repo tristanjo/recover
```

**Download from the release, not from the run's artifacts.** GitHub re-zips artifacts on
download: what you save is a wrapper around the zip that was built, with a different hash
from the one published — so comparing hashes, the one check a recipient can actually
perform, would always fail. Release assets are served byte for byte as uploaded, which is
why the tag build attaches the zip to a release and puts the hash in the release notes.

Python is pinned to 3.12 there: coincurve publishes wheels through 3.13, and on 3.14 the
build would quietly fall back to the slow backend.

## Reading a match

```
Passphrase normalization forms to try: NFKD, NFC, NFD, NFKC
Matched with Unicode normalization form: NFC
Password found: '비밀번호2024'
```

The form matters when moving the funds. NFC and NFD are indistinguishable on screen, and
a wallet that normalizes differently from the one that created the passphrase will derive
a different seed from what looks like the same text.

## Tests

```bash
python -m unittest btcrecover.test.test_passphrase_grammar
```

`count()` is checked against exhaustive generation for every shape of grammar, and
against the numbers `webapp/diagnostic.html` arrives at independently — if those two ever
drift, the quoted estimate stops describing the real search.
