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
