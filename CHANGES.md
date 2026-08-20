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

The patch is also kept standalone at
[`patches/0001-cjk-passphrase-normalization.patch`](patches/0001-cjk-passphrase-normalization.patch)
so it can be re-applied against a fresh upstream checkout.

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
