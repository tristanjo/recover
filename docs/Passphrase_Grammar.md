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
| `digits` | `length: [min, max]` **or** `candidates` | a range covers every string of those lengths, leading zeros kept (`0301` ≠ `301`) |
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

## Command line

```bash
python -m btcrecover.passphrase_grammar config.json --count   # how many candidates
python -m btcrecover.passphrase_grammar config.json --limit 20   # peek at the order
python -m btcrecover.passphrase_grammar config.json --skip 4000000   # resume
```

Candidates come out in a fixed order, so `--skip` resumes exactly where a previous run
stopped. Where no slot is optional the skip is a division rather than a walk, so resuming
four million candidates in is instant.

Slots are indexed rather than materialized: a slot covering every digit string up to
eight characters is 111,111,110 candidates and costs nothing to construct.

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
