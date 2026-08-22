# Passphrase Grammars

When the mnemonic is known and the passphrase is not, the search space is whatever the
owner can still remember about it: a couple of words, roughly how many digits followed,
maybe a symbol. A **grammar** describes that space in a few hundred bytes and expands it
into candidates on demand.

The diagnostic page writes these grammars; `btcrecover.passphrase_grammar` expands
them. Both count candidates the same way, so the estimate the owner is shown is the
search that actually runs.

That page is not in this repository — it is the service rather than the tool, and it lives
in its own. It carries copies of things defined here: the Hangul keystroke tables, the
address-to-derivation-path rules, and the measured cost model behind its time estimate. Its
own tests read this checkout and fail if any of them have drifted, which is the only thing
standing between a customer and a quoted search that is not the one that runs.

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

## Some of these words, not all of them

"It was two or three of these five, I forget which" is a different shape from a slot with
one value: the passphrase ends up with as many parts as were chosen. A `pool` slot says so.

```json
{"type": "pool", "candidates": ["민지", "사랑", "2014", "우리집"], "choose": [2, 3]}
```

gives every 2- and 3-word subset in the order the words were given — 10 of them here — and
each subset joins the candidate as **separate parts**, so separators go between them and
`permute_order` reorders across them. It is not one slot holding a joined string.

`choose` is capped at the number of words given, so `[3, 5]` over three words means three.
Asking for more than exist at the low end is an error rather than an empty search. At most
16 candidates, which bounds the subsets it materializes.

Each subset size is its own tier, which is what keeps the number of parts fixed within a
block — and therefore keeps `count()` a multiplication and `--skip` a division.

Case variants and `keystrokes` do not apply inside a pool: the words go in as given. Someone
who needs both can use the manual editor.

### Measured

A wallet whose passphrase was `사랑2014`, with an owner who remembers four words but not
which two they used:

| | candidates | result |
|---|---|---|
| assuming all four were used | 8 | not found |
| two or three of the four | 20 | **found**, reported as NFC |

## When the IME was never switched on

Korean is typed by pressing Latin keys and letting the input method assemble syllables from
them. With the IME off, those keystrokes arrive as the Latin letters themselves: someone
setting the passphrase `비밀번호` gets `qlalfqjsgh` stored instead.

A password field shows dots, so nothing looks wrong. It keeps working, because the same
wrong keystrokes are typed every time — right up until the owner tries to enter the
passphrase they believe they chose, into a wallet that never saw it.

`"keystrokes": true` on a words slot adds that form after the word's own:

```json
{"type": "words", "candidates": ["비밀번호", "우리집"], "keystrokes": true}
```

yields `비밀번호, qlalfqjsgh, 우리집, dnflwlq`. The word comes first — someone who remembers
Korean most likely did type Korean, and this is the fallback for when they did not.

**A Latin word costs nothing.** Its IME-off form is itself, and duplicates are dropped, so
the option can be left on for an English passphrase without widening the search at all.

Standard 두벌식, which is what an unmodified Korean Windows or macOS types. The tables live
in `btcrecover/hangul_keys.py`, and the diagnostic page carries a copy generated from
them — `btcrecover/test/test_hangul_keys.py` holds the vectors both must satisfy, because a
page that quotes one search while the program runs another is worse than no page.

Only this direction is handled. Going the other way — Latin typed while the IME was on —
would need the composition automaton the IME itself runs, and a half-done version of it
would produce sequences a wallet never stored.

### Measured

A wallet whose passphrase was stored as `qlalfqjsgh2024`, searched with an owner who
remembers `비밀번호2024`:

| | candidates | result |
|---|---|---|
| without the option | 20,000 | exhausted, not found |
| with it | 40,000 | **found at candidate 324**, 0.5s |

## Counting is arithmetic, not enumeration

`count()` multiplies over blocks; it never builds a candidate. That is not a detail — it is
the difference between an estimate a web page can update on every keystroke and one it
cannot show at all.

btcrecover counts by generating. Measured over the same 1,111,110 candidates:

| | counting 1,111,110 |
|---|---|
| `PassphraseGrammar.count()` | **6.6 ms** |
| btcrecover, generating them | 0.9 s |
| btcrecover, the same with one typo enabled (29,130,011) | 59 s |

At a billion candidates btcrecover would spend half an hour deciding how long the search
will take. `embed` therefore passes `--no-eta`: the count is already known exactly, and a
pass over the whole space to draw a progress bar is not worth it. The recovery window shows
progress against the grammar's own number instead.

The same property is what lets the diagnostic page stay responsive. A six-billion
candidate grammar costs it 0.1 ms, and an 8×10¹⁷ one costs the same, because neither is
enumerated. The only part that ever scaled with content was the pool slot, which built its
subsets to count them — sixteen words meant 65,535 of them on every keystroke, 28 ms. It
sums binomials now, and keeps two subsets for sampling characters.

## Why both --no-eta and --no-dupchecks

`embed` passes both, and each is a decision worth stating.

**`--no-eta`** skips btcrecover's counting pass, which counts by generating. The grammar
already knows the number exactly and arithmetically, so the pass buys nothing and costs
everything — see above.

**`--no-dupchecks`** is a real trade, not a free win. With no typo options the grammar
produces no duplicates at all, so it changes nothing: the same 20,002 candidates either way.
With typos on, btcrecover's expansion does repeat itself, and checking would cut the work by
about 29% — 5,094,989 candidates against 7,138,666.

The reason not to take that is what the checking costs, which is roughly a hundred bytes per
distinct candidate and grows with the search:

| expanded candidates | peak memory with duplicate checking |
|---|---|
| 606,387 | 100 MB |
| 5,094,989 | 580 MB |
| 20,295,122 | 2,110 MB |

A hundred million candidates would need ten gigabytes, and a billion a hundred. The searches
where 29% is worth having are exactly the ones where the memory is not available, and a
recovery that dies of exhaustion partway through is worse than one that takes a third longer.
So it stays off, on a customer machine whose memory nobody has measured.

## Typos

The grammar says what the passphrase was built from. Typos say the owner might not have
typed it correctly, which is a different question and gets its own section in the config:

```json
"typos": {"max": 1, "case": true, "swap": true, "delete": true,
          "capslock": false, "repeat": false, "keyboard": false}
```

btcrecover does the mistyping; this only translates. `max` becomes `--typos`, and each
`true` becomes the matching `--typos-*` flag. Nothing is passed unless at least one kind is
asked for, since `--typos` on its own is an error.

`keyboard` uses `typos/us-with-shifts-map.txt`, resolved against the package rather than the
working directory so a frozen build finds it. The unshifted `us-map.txt` is deliberately not
used: it does nothing at all to a passphrase containing a capital — seven variants of
`TREZOr` against thirty-four.

### Stray whitespace

`"whitespace": true` on the passphrase section also tries each candidate with a space at
the front, at the end, and at both. A field shows dots, so a space there is invisible, and
it is easy to acquire: typed by accident, or picked up by a copy-paste that took one
character too many.

It lives with the grammar rather than with the typos, because it is not a mistyping, and it
is applied **outermost** — every candidate is tried untouched before any is tried with a
space attached. Four times the work in the worst case, and no delay at all to a passphrase
that had none.

### What each one costs

Measured with `btcrecover --listpass`, not derived:

| | `minji2014` (9 chars, 5 letters) | `비밀번호2024` (8 chars, no letters) |
|---|---|---|
| none | 1 | 1 |
| `case` | 6 | **1** |
| `capslock` | 2 | **1** |
| `swap` | 9 | 8 |
| `delete` | 10 | 9 |
| `repeat` | 10 | 9 |
| `keyboard` | 34 | 21 |
| `leet` | 5 | **1** |
| `replace` | 316 | 285 |
| `insert` | 352 | 321 |
| all five, `max: 1` | 33 | 24 |
| all five, `max: 2` | 486 | 241 |
| all five, `max: 3` | 4,222 | 1,360 |

**`case`, `capslock` and `leet` do nothing to Hangul** — there is no letter case, and the leet
map replaces Latin letters. Offering them for a Korean passphrase costs nothing and gains
nothing, so the diagnostic page disables them when the sample contains no Latin letters.

`replace` and `insert` try lowercase letters and digits (`%n`). The full printable set is
nearly three times the work — 838 variants of a nine-character passphrase against 316 — for
characters a slip of the finger rarely produces.

`keyboard` and `leet` are both `--typos-map`, which takes **one** file and keeps only the
last given. Asking for both would silently drop one, so they are merged into a single map
first; btcrecover's parser accumulates replacements per character, so a character listed in
both ends up with the union of them.

The page's estimate is an upper bound: it counts every combination of up to `max` changes,
while btcrecover discards variants that collide. On the nine-character sample that is 529
against 486 at two typos. Quoting slightly long is the safe direction.

## Priority order

Candidates are emitted in likelihood order by default. A digit run is tried as the things
people actually put in passphrases, in this order:

1. **a year**, 1900–2099, for a four-digit run — a birth year, a wedding year, the year
   someone bought their first coin
2. **a date** — `MMDD` for four digits, `YYMMDD` for six, which is how a Korean ID number
   starts and how a great many people write a birthday
3. **something chosen to be memorable** — all one digit, a run up or down, a repeating pair
4. everything else

Each tier is index ranges rather than a list of values, since a tier over eight digits would
be a hundred million of them, and the ranges are bisected rather than walked.

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

### Measuring it

`utilities/passphrase_rank_benchmark.py` reports where the true passphrase lands, with the
ordering on and off, over a fixed set of cases:

```bash
python utilities/passphrase_rank_benchmark.py
```

Without a number for "sooner", every change to the model is an assertion — it looks more
principled, so it must be better. Run this before and after instead.

Current state, 19 cases: median position **20.15% → 1.25%** of the space, and **2 → 15** of
them inside the first 10%.

The cases are hand-written, and that is the honest limit of the tool: they encode what one
person thinks passphrase construction looks like, so a model tuned until the number is
beautiful has been tuned to those guesses. It is sound for catching a change that makes
things worse, and for comparing two models on the same set. Replace the cases with real ones
as soon as there are real ones.

It is also what keeps the trade-offs visible. Adding the date tiers made two cases faster
and two slower, and the six-digit tier is only worth it if six digits really are a birthday
more often than not:

| six-digit answer | plain | ordered | |
|---|---|---|---|
| `880301` (birthday) | 880,302 | 32,269 | 27x sooner |
| `011225` (birthday) | 11,226 | 726 | 15x sooner |
| `473916` (random) | 473,917 | 493,011 | 1.0x slower |
| `112233` (neither) | 112,234 | 144,545 | 1.3x slower |

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
against the numbers the diagnostic page arrives at independently — if those two ever
drift, the quoted estimate stops describing the real search.
