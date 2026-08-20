# Non-ASCII (CJK) BIP39 Passphrases

## The problem

[BIP39](https://github.com/bitcoin/bips/blob/master/bip-0039/bip-0039.mediawiki) requires the
passphrase to be **NFKD**-normalized before it is used as the PBKDF2 salt. Not every wallet did
that — several hashed whatever the user's keyboard produced.

For an ASCII passphrase this makes no difference: all four Unicode normalization forms give the
same bytes. For Hangul, Kana, or anything else with composed and decomposed representations, they
do not:

| Form | UTF-8 bytes of `비밀번호2024` | Resulting seed |
|---|---|---|
| NFC / NFKC | 16 | `320156d798442c3c…` |
| NFD / NFKD | 34 | `d0a02b83268dd255…` |

Two different seeds means two entirely different wallets. If the original wallet stored the NFC
form, BTCRecover's spec-compliant NFKD-only behaviour will **never** find it — even when both the
mnemonic and the passphrase are exactly correct.

Korean and Japanese IMEs on Windows typically produce NFC, and macOS filesystem APIs produce NFD,
so a passphrase can also change form simply by being copied between machines.

## The fix

`--passphrase-normalizations` selects which forms to try:

```bash
python seedrecover.py --wallet-type bip39 --language en \
  --mnemonic "..." --passphrase-arg "비밀번호2024" \
  --addrs 12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu \
  --passphrase-normalizations all
```

* Default is `NFKD`, which is what BIP39 specifies — existing behaviour is unchanged.
* `all` tries `NFKD, NFC, NFD, NFKC`, in that order (the spec-compliant form first).
* A comma-separated subset also works, e.g. `--passphrase-normalizations nfkd,nfc`.

Duplicate salts are dropped, so the real cost is lower than it looks:

| Passphrase | Salts searched with `all` |
|---|---|
| ASCII (`btcr-test-password`) | 1 — no extra cost at all |
| Hangul (`비밀번호2024`) | 2 — NFC and NFKC agree, as do NFD and NFKD |

Worst case is 4× the work, and only for passphrases mixing scripts with compatibility characters
(full-width forms, ligatures, circled numerals).

## Reading the result

Because NFC and NFD are **indistinguishable on screen**, a match reports which form it came from:

```
***MATCHING SEED FOUND***, Matched with BIP39 Passphrase: 비밀번호2024 [NFC]
```

This matters when moving funds: the recovered passphrase has to be entered into the new wallet in
the same form. If the label says `[NFC]` and the destination wallet normalizes to NFKD, typing the
"same" passphrase will produce a different wallet.

## Scope

Applies to BIP39 wallets (and the many coins deriving from `WalletBIP39`). Electrum 2.x is
unaffected: it defines its own normalization — NFKD, lowercased, combining marks stripped,
whitespace collapsed — which is applied consistently by Electrum itself. aezeed salts the
passphrase verbatim and is likewise unaffected.

## Tests

`btcrecover/test/test_cjk_passphrase.py` pins all of the above, including a ground-truth generator
that rebuilds the expected addresses straight from the BIP39/BIP32 specs without importing
btcrecover — so a bug in the normalization under test cannot mask itself.

```bash
python -m unittest btcrecover.test.test_cjk_passphrase -v
```
