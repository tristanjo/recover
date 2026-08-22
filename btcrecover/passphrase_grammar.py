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

from btcrecover.hangul_keys import to_keystrokes

__all__ = ["PassphraseGrammar", "GrammarError"]


class GrammarError(ValueError):
    """The grammar document is malformed or describes nothing."""


# Digit runs that look like a year are tried before the rest of their length. This is
# the whole of the priority model for now: a deliberately small, contiguous prior that
# can be stated and defended ("people put years in passphrases"), sitting where richer
# statistics from real cases will replace it. Keep any replacement expressible as index
# ranges -- that is what keeps --skip a division instead of a walk.
YEAR_RANGE = (1900, 2100)
YEAR_DIGITS = 4

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

    def priority_tiers(self):
        """The slot's non-empty values, split into groups to try in order.

        Each tier is a list of (start, stop) index ranges. Ranges rather than value
        lists so that a tier covering ten million values stays free to construct, and
        so an index within a tier maps to a value in constant time.
        """
        return [[(0, self.nonempty_len)]]


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

    def priority_tiers(self):
        """Year-like values first, then everything else, both as index ranges.

        Splitting a length at the year range leaves the remainder as two contiguous
        pieces, so no tier ever needs to enumerate what it excludes.
        """
        if not self.min_len <= YEAR_DIGITS <= self.max_len:
            return [[(0, self.nonempty_len)]]

        lo, hi, offset, years, rest = YEAR_RANGE[0], YEAR_RANGE[1], 0, [], []
        for k in range(len(self.bounds)):
            length = self.min_len + k
            start, stop = offset, self.bounds[k]
            if length == YEAR_DIGITS:
                years.append((start + lo, start + hi))
                rest.append((start, start + lo))
                rest.append((start + hi, stop))
            else:
                rest.append((start, stop))
            offset = stop
        return [years, [r for r in rest if r[1] > r[0]]]


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
        values = []
        for w in words:
            for c in cases:
                values.append(CASES[c](w))
            if spec.get("keystrokes"):
                # What a keyboard sends for this word with the Korean IME switched off.
                # Appended after the word's own forms: someone who remembers a Korean word
                # most likely did type Korean, and this is the fallback for when they did not.
                values.append(to_keystrokes(w))
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
        # Order by likelihood rather than by odometer. Off gives the raw product order,
        # which is what a test wants when it needs to compare the two.
        self.priority = bool(pp.get("priority", True))
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

    def assignment_count(self):
        """Number of slot-value combinations, before ordering and separators."""
        n = 1
        for slot in self.slots:
            n *= len(slot)
        return n

    # ---- priority order -------------------------------------------------

    def _slot_tiers(self, slot):
        """(index ranges, is-the-empty-tier) for each tier of `slot`, in trying order."""
        if not self.priority:
            return [([(0, len(slot))], False)]   # one flat tier; emptiness varies inside it
        tiers = [(ranges, False) for ranges in slot.priority_tiers()]
        if slot.optional:
            # a slot the user is unsure about is tried present before absent
            tiers.append(([(slot.nonempty_len, slot.nonempty_len + 1)], True))
        return tiers

    @staticmethod
    def _tier_size(ranges):
        return sum(stop - start for start, stop in ranges)

    @staticmethod
    def _tier_index(ranges, i):
        """Map a position within a tier to an index into the slot."""
        for start, stop in ranges:
            width = stop - start
            if i < width:
                return start + i
            i -= width
        raise IndexError(i)

    def _blocks(self):
        """Every combination of per-slot tiers, cheapest first.

        Cost is the sum of the tier numbers, so a candidate that is a second choice in
        one slot comes before one that is a second choice in two. Within a block the
        tiers are fixed, and therefore so is whether each slot is empty -- which is what
        lets `generate` divide its way into a block instead of walking there.
        """
        all_tiers = [self._slot_tiers(s) for s in self.slots]
        counts = [len(t) for t in all_tiers]
        for cost in range(sum(c - 1 for c in counts) + 1):
            for vector in itertools.product(*(range(c) for c in counts)):
                if sum(vector) != cost:
                    continue
                ranges  = [all_tiers[i][t][0] for i, t in enumerate(vector)]
                empties = [all_tiers[i][t][1] for i, t in enumerate(vector)]
                yield ranges, empties, [self._tier_size(r) for r in ranges]

    # ---- generation -----------------------------------------------------

    def _assignment(self, ranges, sizes, index):
        """Decode a mixed-radix index into one value per slot. Last slot varies fastest."""
        values = [None] * len(self.slots)
        for i in range(len(self.slots) - 1, -1, -1):
            index, pos = divmod(index, sizes[i])
            values[i] = self.slots[i][self._tier_index(ranges[i], pos)]
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

        Order is by priority when the grammar asks for it: the values a slot considers
        likely come before the rest, and a candidate settling for a second choice in one
        slot comes before one settling in two. This changes only the order -- the set of
        candidates, and so `count()`, is the same either way.
        """
        if skip < 0:
            raise ValueError("skip must be >= 0")
        produced = 0
        flexible_emptiness = not self.priority and any(s.optional for s in self.slots)

        for ranges, empties, sizes in self._blocks():
            assignments = 1
            for size in sizes:
                assignments *= size
            if not assignments:
                continue

            # Outputs per assignment, where the block fixes it. Only a flat tier holding
            # both real values and the empty one leaves it varying.
            per_assignment = None
            if not flexible_emptiness:
                per_assignment = self._outputs_for(len(self.slots) - sum(empties))
                if not per_assignment:
                    continue          # every slot in this block is empty
                block_total = assignments * per_assignment
                if skip >= block_total:
                    skip -= block_total
                    continue

            index = 0
            if per_assignment and skip:
                index, skip = divmod(skip, per_assignment)

            while index < assignments:
                values = self._assignment(ranges, sizes, index)
                index += 1
                if skip and not per_assignment:
                    num_parts = sum(1 for v in values if v)
                    if not num_parts:
                        continue
                    here = self._outputs_for(num_parts)
                    if here <= skip:
                        skip -= here
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
