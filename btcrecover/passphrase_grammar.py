#!/usr/bin/env python
# -*- coding: utf-8 -*-

# passphrase_grammar.py -- expand a passphrase grammar into candidate passphrases
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

"""Turns what a user half-remembers about their passphrase into candidates.

The grammar is a small JSON document -- a list of slots, the separators that may
join them, and whether their order is known. It is deliberately *not* an expanded
list of passphrases: a grammar describing a billion candidates is a few hundred
bytes, while the same list would be tens of gigabytes.

Slots are random-access rather than materialized, so a slot covering every 8-digit
number costs nothing until its values are actually asked for. Candidates stream
out in a fixed order, which makes an interrupted search resumable.

    python -m btcrecover.passphrase_grammar config.json --count
    python -m btcrecover.passphrase_grammar config.json | \\
        python btcrecover.py --wallet-type bip39 --mnemonic "..." \\
            --addrs 1... --passwordlist -
"""

import itertools, json, math, sys

__all__ = ["PassphraseGrammar", "GrammarError"]


class GrammarError(ValueError):
    """The grammar document is malformed or describes nothing."""


# Case transforms a "words" slot may apply, in the order they are tried.
CASES = {
    "asis":  lambda w: w,
    "lower": lambda w: w.lower(),
    "title": lambda w: w[:1].upper() + w[1:].lower(),
    "upper": lambda w: w.upper(),
}


class _Slot:
    """One position in the passphrase. Indexable so huge slots stay unmaterialized."""

    def __init__(self, optional=False):
        self.optional = optional

    def __len__(self):
        """Number of values, counting the empty one contributed by `optional`."""
        return self.nonempty_len + (1 if self.optional else 0)

    def __getitem__(self, i):
        if self.optional and i == self.nonempty_len:
            return ""          # the empty value always sorts last, so dropping
        return self.value_at(i)  # `optional` never renumbers the real values


class _ListSlot(_Slot):
    """A slot backed by an explicit list of candidates."""

    def __init__(self, values, optional=False):
        super().__init__(optional)
        # dedupe while keeping the order the user gave, which is their priority order
        seen, ordered = set(), []
        for v in values:
            if v and v not in seen:
                seen.add(v)
                ordered.append(v)
        self.values = ordered
        self.nonempty_len = len(ordered)

    def value_at(self, i):
        return self.values[i]


class _DigitsSlot(_Slot):
    """Every digit string whose length falls in [min_len, max_len], shortest first.

    Leading zeros are kept: someone who wrote 0301 for a birthday did not write 301.
    """

    def __init__(self, min_len, max_len, optional=False):
        super().__init__(optional)
        if not 1 <= min_len <= max_len:
            raise GrammarError("digit slot needs 1 <= length[0] <= length[1], got "
                               "[{}, {}]".format(min_len, max_len))
        self.min_len, self.max_len = min_len, max_len
        # cumulative counts, so value_at() can find the right length by bisection
        self.bounds, total = [], 0
        for L in range(min_len, max_len + 1):
            total += 10 ** L
            self.bounds.append(total)
        self.nonempty_len = total

    def value_at(self, i):
        offset = 0
        for k, bound in enumerate(self.bounds):
            if i < bound:
                L = self.min_len + k
                return str(i - offset).zfill(L)
            offset = bound
        raise IndexError(i)


def _build_slot(spec):
    """One slot of a config.json `passphrase.slots` array."""
    if not isinstance(spec, dict):
        raise GrammarError("each slot must be an object, got " + type(spec).__name__)
    kind = spec.get("type")
    optional = bool(spec.get("optional"))

    if kind == "words":
        words = [w for w in spec.get("candidates", []) if w]
        cases = spec.get("cases") or ["asis"]
        for c in cases:
            if c not in CASES:
                raise GrammarError("unknown case transform '{}'; choose from {}"
                                   .format(c, ", ".join(CASES)))
        # word-major, so every form of the first word is tried before the second
        values = [CASES[c](w) for w in words for c in cases]
        return _ListSlot(values, optional)

    if kind == "digits":
        if "length" in spec:
            length = spec["length"]
            if not (isinstance(length, (list, tuple)) and len(length) == 2):
                raise GrammarError("digit slot 'length' must be [min, max]")
            return _DigitsSlot(int(length[0]), int(length[1]), optional)
        return _ListSlot([str(v) for v in spec.get("candidates", [])], optional)

    if kind in ("symbols", "fixed"):
        return _ListSlot([str(v) for v in spec.get("candidates", [])], optional)

    raise GrammarError("unknown slot type '{}'; expected words, digits, symbols or fixed"
                       .format(kind))


class PassphraseGrammar:
    """Expands a passphrase grammar into candidates, lazily and in a fixed order.

    Empty slots drop out along with the separator that would have followed them, so
    an optional slot yields "alpha-beta" rather than "alpha--beta". A candidate built
    from fewer than two parts has nowhere to put a separator, and is emitted once
    rather than once per separator.
    """

    def __init__(self, spec):
        if not isinstance(spec, dict):
            raise GrammarError("grammar must be a JSON object")
        pp = spec.get("passphrase", spec)

        self.slots = [s for s in (_build_slot(x) for x in pp.get("slots", [])) if len(s)]
        if not self.slots:
            raise GrammarError("grammar has no slots with any candidates")

        seps = pp.get("separators", [""])
        # dedupe but keep order; an empty separator list would silently drop candidates
        self.separators = list(dict.fromkeys(seps)) or [""]
        self.permute = bool(pp.get("permute_order"))
        self.normalizations = pp.get("normalizations") or ["NFKD"]

    @classmethod
    def from_file(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return cls(json.load(f))
            except json.JSONDecodeError as e:
                raise GrammarError("{} is not valid JSON: {}".format(path, e))

    # ---- counting -------------------------------------------------------

    def _outputs_for(self, num_parts):
        """How many candidates one assignment with `num_parts` non-empty slots yields."""
        if num_parts == 0:
            return 0   # every slot went empty; there is no passphrase to try
        arrangements = math.factorial(num_parts) if self.permute else 1
        separators = len(self.separators) if num_parts >= 2 else 1
        return arrangements * separators

    def count(self):
        """Exact number of candidates `generate()` will yield.

        Assumes no two slots can produce the same string; where they can, permuting
        them produces a duplicate and the true number is slightly lower.
        """
        optional = [i for i, s in enumerate(self.slots) if s.optional]
        total = 0
        # Each subset of the optional slots that goes empty gives a different part
        # count, and so a different number of orderings and separator placements.
        for empties in range(len(optional) + 1):
            for empty_set in itertools.combinations(optional, empties):
                ways = 1
                for i, slot in enumerate(self.slots):
                    if i not in empty_set:
                        ways *= slot.nonempty_len
                total += ways * self._outputs_for(len(self.slots) - empties)
        return total

    def _uniform_outputs(self):
        """Outputs per assignment, when every assignment yields the same number.

        Only optional slots can vary it -- they change how many parts a candidate has,
        and so how many orderings and separator placements it gets. Without them the
        count is constant, and `skip` becomes a division instead of a walk.
        """
        if any(slot.optional for slot in self.slots):
            return None
        return self._outputs_for(len(self.slots))

    def assignment_count(self):
        """Number of slot-value combinations, before ordering and separators."""
        n = 1
        for slot in self.slots:
            n *= len(slot)
        return n

    # ---- generation -----------------------------------------------------

    def _assignment(self, index):
        """Decode a mixed-radix index into one value per slot. Last slot varies fastest."""
        values = [None] * len(self.slots)
        for i in range(len(self.slots) - 1, -1, -1):
            slot = self.slots[i]
            index, pos = divmod(index, len(slot))
            values[i] = slot[pos]
        return values

    def _expand(self, values):
        """Every candidate one assignment produces."""
        parts = [v for v in values if v]
        if not parts:
            return
        orders = itertools.permutations(parts) if (self.permute and len(parts) > 1) else (tuple(parts),)
        for order in orders:
            if len(order) >= 2:
                for sep in self.separators:
                    yield sep.join(order)
            else:
                yield order[0]

    def generate(self, skip=0, limit=None):
        """Yields candidates in a fixed order, resumable via `skip`.

        Skipping walks assignments rather than candidates -- each assignment's output
        count is known in advance -- so resuming is cheap even far into a long search.
        """
        if skip < 0:
            raise ValueError("skip must be >= 0")
        produced = 0
        index = 0
        total_assignments = self.assignment_count()

        per_assignment = self._uniform_outputs()
        if skip and per_assignment:
            # Jump straight to the right assignment rather than counting up to it; this
            # is what keeps resuming a billion candidates in cheap.
            index, skip = divmod(skip, per_assignment)
            index = min(index, total_assignments)

        while index < total_assignments:
            values = self._assignment(index)
            index += 1
            if skip:
                # An assignment whose output we would discard entirely can be counted
                # off without building any of its strings.
                num_parts = sum(1 for v in values if v)
                if not num_parts:
                    continue
                produced_here = self._outputs_for(num_parts)
                if produced_here <= skip:
                    skip -= produced_here
                    continue
            for candidate in self._expand(values):
                if skip:
                    skip -= 1
                    continue
                yield candidate
                produced += 1
                if limit is not None and produced >= limit:
                    return

    def __iter__(self):
        return self.generate()


def _main(argv):
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m btcrecover.passphrase_grammar",
        description="Expand a passphrase grammar (config.json) into candidate passphrases.")
    parser.add_argument("config", help="the grammar, as written by the diagnostic web tool")
    parser.add_argument("--count", action="store_true", help="print the number of candidates and exit")
    parser.add_argument("--skip", type=int, default=0, metavar="N", help="resume, discarding the first N candidates")
    parser.add_argument("--limit", type=int, default=None, metavar="N", help="stop after N candidates")
    args = parser.parse_args(argv)

    try:
        grammar = PassphraseGrammar.from_file(args.config)
    except (GrammarError, OSError) as e:
        sys.exit("error: " + str(e))

    if args.count:
        print(grammar.count())
        return 0

    out = sys.stdout
    try:
        for candidate in grammar.generate(skip=args.skip, limit=args.limit):
            out.write(candidate + "\n")
    except BrokenPipeError:
        # the consumer stopped reading -- e.g. btcrecover found the passphrase
        try:
            out.close()
        except BrokenPipeError:
            pass
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
