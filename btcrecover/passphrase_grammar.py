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

import bisect, itertools, json, math, sys

from btcrecover.hangul_keys import to_keystrokes

__all__ = ["PassphraseGrammar", "GrammarError"]


_CUMULATIVE_CACHE = {}


def _cumulative_widths(ranges):
    """Running total of range widths, memoised: tier range lists are built once and reused
    for every candidate drawn from them."""
    key = id(ranges)
    cached = _CUMULATIVE_CACHE.get(key)
    if cached is None or cached[0] is not ranges:
        totals, running = [], 0
        for start, stop in ranges:
            running += stop - start
            totals.append(running)
        _CUMULATIVE_CACHE[key] = cached = (ranges, totals)
    return cached[1]


def complement_ranges(total, taken):
    """Everything in [0, total) that `taken` -- sorted, disjoint ranges -- does not cover.

    Computed from the ranges rather than by walking the space: the space is as large as ten
    to the eighth, and the ranges number in the thousands at worst.
    """
    gaps, cursor = [], 0
    for start, stop in taken:
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, stop)
    if cursor < total:
        gaps.append((cursor, total))
    return gaps


def ranges_from(values):
    """Compress a sorted iterable of indexes into (start, stop) runs.

    Tiers have to be expressible as index ranges -- that is what keeps a tier covering ten
    million values free to construct and constant-time to index into.
    """
    ranges = []
    for value in values:
        if ranges and ranges[-1][1] == value:
            ranges[-1][1] = value + 1
        else:
            ranges.append([value, value + 1])
    return [tuple(r) for r in ranges]


class GrammarError(ValueError):
    """The grammar document is malformed or describes nothing."""


# Digit runs that look like a year are tried before the rest of their length. This is
# the whole of the priority model for now: a deliberately small, contiguous prior that
# can be stated and defended ("people put years in passphrases"), sitting where richer
# statistics from real cases will replace it. Keep any replacement expressible as index
# ranges -- that is what keeps --skip a division instead of a walk.
YEAR_RANGE = (1900, 2100)
YEAR_DIGITS = 4

DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)   # February kept generous


def _date_values(length):
    """Digit strings of `length` that read as a date, as integers.

    Four digits: MMDD. Six: YYMMDD, which is how a Korean ID number starts and how a great
    many people write a birthday.
    """
    if length == 4:
        return [month * 100 + day
                for month in range(1, 13)
                for day in range(1, DAYS_IN_MONTH[month - 1] + 1)]
    if length == 6:
        return [(year * 100 + month) * 100 + day
                for year in range(100)
                for month in range(1, 13)
                for day in range(1, DAYS_IN_MONTH[month - 1] + 1)]
    return []


def _memorable_values(length):
    """Digit strings people reach for when they want something they cannot forget:
    all one digit, a run up or down, a repeating pair."""
    out = set()
    for digit in range(10):
        out.add(int(str(digit) * length))                       # 0000, 1111
    for start in range(10):
        up = "".join(str((start + i) % 10) for i in range(length))
        out.add(int(up))                                        # 1234, 7890
        out.add(int(up[::-1]))                                  # 4321
    if length % 2 == 0:
        for pair in range(100):
            out.add(int(("%02d" % pair) * (length // 2)))        # 1212, 121212
    return sorted(v for v in out if v < 10 ** length)

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
        """What a digit run is most likely to be, in order: a year, then a date, then
        something chosen to be memorable, then anything else.

        Each tier is index ranges, never a list of values -- a tier over eight digits would
        be a hundred million of them. The ranges are built once here, by walking each
        length's block and asking what each value looks like.
        """
        by_tier = [[], [], []]      # years, dates, memorable
        claimed = set()
        offset = 0
        for k in range(len(self.bounds)):
            length = self.min_len + k
            start, stop = offset, self.bounds[k]
            offset = stop

            groups = []
            if length == YEAR_DIGITS:
                groups.append(range(YEAR_RANGE[0], YEAR_RANGE[1]))
            else:
                groups.append(())
            groups.append(_date_values(length))
            groups.append(_memorable_values(length))

            for tier, values in enumerate(groups):
                fresh = sorted(start + v for v in values if start + v not in claimed)
                claimed.update(fresh)
                by_tier[tier].extend(fresh)

        tiers = [ranges_from(sorted(t)) for t in by_tier if t]
        if not tiers:
            return [[(0, self.nonempty_len)]]
        rest = complement_ranges(self.nonempty_len,
                                 sorted(r for tier in tiers for r in tier))
        return tiers + ([rest] if rest else [])


# The alphabets a charset slot can be built from. Ordered so that the values a slot yields
# start with the characters someone is most likely to have used.
CHARSETS = {
    "lower":   "abcdefghijklmnopqrstuvwxyz",
    "upper":   "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "digits":  "0123456789",
    "symbols": "!@#$%^&*()-_=+[]{};:,.?/",
}


class _CharsetSlot(_Slot):
    """Every string over a chosen alphabet whose length is in [min_len, max_len].

    For the person who remembers nothing about a run of characters except roughly how long
    it was. Every other slot type asks what the value might have been; this one is what to
    reach for when the honest answer is "no idea".

    It grows the way exhaustive search grows, and that is the point of being able to say it:
    four lower-case letters is 475,254, and adding upper case takes the same four characters
    to 7,454,980. A customer who cannot express this at all gets no answer; one who can gets
    a number and a time, which is what they came for even when the answer is "not worth
    starting".

    Shortest first, and within a length, counting in base-N over the alphabet.
    """

    def __init__(self, alphabet, min_len, max_len, optional=False):
        super().__init__(optional)
        seen, ordered = set(), []
        for c in alphabet:
            if c not in seen:
                seen.add(c)
                ordered.append(c)
        if not ordered:
            raise GrammarError("charset slot has no characters to draw from")
        if not 1 <= min_len <= max_len:
            raise GrammarError("charset slot needs 1 <= length[0] <= length[1], got "
                               "[{}, {}]".format(min_len, max_len))
        self.alphabet = "".join(ordered)
        self.min_len, self.max_len = min_len, max_len
        base = len(self.alphabet)
        # cumulative counts, so value_at() finds the right length by walking these
        self.bounds, total = [], 0
        for L in range(min_len, max_len + 1):
            total += base ** L
            self.bounds.append(total)
        self.nonempty_len = total

    def value_at(self, i):
        base = len(self.alphabet)
        offset = 0
        for k, bound in enumerate(self.bounds):
            if i < bound:
                length = self.min_len + k
                n = i - offset
                out = []
                for _ in range(length):
                    n, r = divmod(n, base)
                    out.append(self.alphabet[r])
                return "".join(reversed(out))
            offset = bound
        raise IndexError(i)

    def priority_tiers(self):
        """One tier per length, shortest first.

        Nothing inside a length is more likely than anything else -- that is what "no idea"
        means -- but a shorter passphrase is likelier than a longer one, and exhausting the
        short ones first costs nothing.
        """
        tiers, offset = [], 0
        for bound in self.bounds:
            tiers.append([(offset, bound)])
            offset = bound
        return tiers


class _PoolSlot(_Slot):
    """Some of these words, not necessarily all of them.

    "It was two or three of these five, I forget which" is not a slot with one value -- the
    passphrase ends up with as many parts as were chosen. Each value here is therefore a
    tuple of words rather than a string, and the parts join with everything else.

    Subsets are materialized: the whole point is a handful of remembered words, and the cap
    below bounds that at a few tens of thousands of tuples.
    """

    MAX_CANDIDATES = 16

    def __init__(self, words, choose, optional=False):
        super().__init__(optional)
        seen, ordered = set(), []
        for w in words:
            if w and w not in seen:
                seen.add(w)
                ordered.append(w)
        if len(ordered) > self.MAX_CANDIDATES:
            raise GrammarError("a pool takes at most {} words, got {}"
                               .format(self.MAX_CANDIDATES, len(ordered)))
        low, high = int(choose[0]), int(choose[1])
        if not 1 <= low <= high:
            raise GrammarError("pool 'choose' must be [min, max] with 1 <= min <= max, got "
                               "[{}, {}]".format(low, high))
        high = min(high, len(ordered))
        if low > high:
            raise GrammarError("pool asks for at least {} words but only {} were given"
                               .format(low, len(ordered)))

        # Grouped by how many words were taken, smallest first, and the ranges recorded so
        # each size can be its own tier -- which is what keeps the part count fixed within
        # a block, and so keeps --skip a division.
        self.values, self.sizes = [], []
        for k in range(low, high + 1):
            start = len(self.values)
            self.values.extend(itertools.combinations(ordered, k))
            self.sizes.append((k, start, len(self.values)))
        self.words = ordered
        self.nonempty_len = len(self.values)

    def value_at(self, i):
        return self.values[i]

    def priority_tiers(self):
        return [[(start, stop)] for _, start, stop in self.sizes]

    def tiers_by_size(self):
        """(parts contributed, index ranges) for each subset size, smallest first."""
        return [(k, [(start, stop)]) for k, start, stop in self.sizes]


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

    if kind == "pool":
        return _PoolSlot([str(w) for w in spec.get("candidates", []) if w],
                         spec.get("choose") or [1, 1], optional)

    if kind == "digits":
        if "length" in spec:
            length = spec["length"]
            if not (isinstance(length, (list, tuple)) and len(length) == 2):
                raise GrammarError("digit slot 'length' must be [min, max]")
            return _DigitsSlot(int(length[0]), int(length[1]), optional)
        return _ListSlot([str(v) for v in spec.get("candidates", [])], optional)

    if kind == "charset":
        names = spec.get("sets") or ["lower"]
        alphabet = ""
        for name in names:
            if name not in CHARSETS:
                raise GrammarError("unknown charset '{}'; choose from {}"
                                   .format(name, ", ".join(CHARSETS)))
            alphabet += CHARSETS[name]
        alphabet += str(spec.get("extra") or "")
        length = spec.get("length")
        if not (isinstance(length, (list, tuple)) and len(length) == 2):
            raise GrammarError("charset slot 'length' must be [min, max]")
        return _CharsetSlot(alphabet, int(length[0]), int(length[1]), optional)

    if kind in ("symbols", "fixed"):
        return _ListSlot([str(v) for v in spec.get("candidates", [])], optional)

    raise GrammarError("unknown slot type '{}'; expected words, pool, digits, charset, "
                       "symbols or fixed".format(kind))


# A field shows dots, so a space at either end is invisible -- and it is easy to acquire:
# typed by accident, or picked up by a copy-paste that took one character too many. Tried
# outermost, so a passphrase with no stray space is reached exactly as soon as it was before.
WHITESPACE_FORMS = ("{}", "{} ", " {}", " {} ")


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
        # Also try the candidate with a space at either end, or both.
        self.whitespace = bool(pp.get("whitespace"))
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
        """Exact number of candidates `generate()` will yield."""
        return self._core_count() * len(self._whitespace_forms())

    def _whitespace_forms(self):
        return WHITESPACE_FORMS if self.whitespace else ("{}",)

    def _core_count(self):
        """The count before stray whitespace is considered.

        Every block has a fixed number of parts, so each contributes a product rather than
        an enumeration. Assumes no two slots can produce the same string; where they can,
        permuting them makes a duplicate and the true number is slightly lower.
        """
        total = 0
        for _ranges, parts, sizes in self._blocks():
            assignments = 1
            for size in sizes:
                assignments *= size
            total += assignments * self._outputs_for(parts)
        return total

    def assignment_count(self):
        """Number of slot-value combinations, before ordering and separators."""
        n = 1
        for slot in self.slots:
            n *= len(slot)
        return n

    # ---- priority order -------------------------------------------------

    def _slot_tiers(self, slot):
        """(index ranges, parts contributed) for each tier of `slot`, in trying order.

        Every tier declares how many parts it puts into a candidate: one for an ordinary
        slot, none for the empty tier of an optional one, and k for a pool tier that takes
        k words. Fixing that per tier is what lets `generate` divide its way into a block
        instead of walking there, and what lets `count` multiply instead of enumerate.

        Pools and optional slots are tiered whether or not priority ordering was asked for,
        because the arithmetic depends on it; priority only decides the order of the rest.
        """
        if isinstance(slot, _PoolSlot):
            tiers = [(ranges, k) for k, ranges in slot.tiers_by_size()]
        elif self.priority:
            tiers = [(ranges, 1) for ranges in slot.priority_tiers()]
        else:
            tiers = [([(0, slot.nonempty_len)], 1)]
        if slot.optional:
            # a slot the user is unsure about is tried present before absent
            tiers.append(([(slot.nonempty_len, slot.nonempty_len + 1)], 0))
        return tiers

    @staticmethod
    def _tier_size(ranges):
        return sum(stop - start for start, stop in ranges)

    @staticmethod
    def _tier_index(ranges, i):
        """Map a position within a tier to an index into the slot.

        Bisected rather than walked: a tier describing "every valid MMDD" is a dozen
        ranges and one describing "every YYMMDD" is over a thousand, and this is called
        once per slot per candidate.
        """
        if len(ranges) == 1:
            start, stop = ranges[0]
            if 0 <= i < stop - start:
                return start + i
            raise IndexError(i)
        cumulative = _cumulative_widths(ranges)
        k = bisect.bisect_right(cumulative, i)
        if k >= len(ranges):
            raise IndexError(i)
        start, _stop = ranges[k]
        return start + i - (cumulative[k - 1] if k else 0)

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
                ranges = [all_tiers[i][t][0] for i, t in enumerate(vector)]
                parts  = sum(all_tiers[i][t][1] for i, t in enumerate(vector))
                yield ranges, parts, [self._tier_size(r) for r in ranges]

    # ---- generation -----------------------------------------------------

    def _assignment(self, ranges, sizes, index):
        """Decode a mixed-radix index into one value per slot. Last slot varies fastest."""
        values = [None] * len(self.slots)
        for i in range(len(self.slots) - 1, -1, -1):
            index, pos = divmod(index, sizes[i])
            values[i] = self.slots[i][self._tier_index(ranges[i], pos)]
        return values

    def _expand(self, values):
        """Every candidate one assignment produces.

        A pool slot hands back a tuple of words, which join the candidate as separate parts
        rather than as one -- separators go between them and ordering applies across them.
        """
        parts = []
        for v in values:
            if isinstance(v, tuple):
                parts.extend(p for p in v if p)
            elif v:
                parts.append(v)
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

        Stray whitespace is the outermost loop: every candidate is tried untouched before
        any is tried with a space attached, so asking for it never delays the case where
        there was none.
        """
        if skip < 0:
            raise ValueError("skip must be >= 0")
        forms = self._whitespace_forms()
        if len(forms) == 1:
            yield from self._generate_core(skip, limit)
            return

        base = self._core_count()
        produced = 0
        for form in forms:
            if skip >= base:
                skip -= base
                continue
            remaining = None if limit is None else limit - produced
            for candidate in self._generate_core(skip, remaining):
                yield form.format(candidate)
                produced += 1
                if limit is not None and produced >= limit:
                    return
            skip = 0

    def _generate_core(self, skip=0, limit=None):
        """Yields candidates in a fixed order, resumable via `skip`.

        Order is by priority when the grammar asks for it: the values a slot considers
        likely come before the rest, and a candidate settling for a second choice in one
        slot comes before one settling in two. This changes only the order -- the set of
        candidates, and so `count()`, is the same either way.
        """
        if skip < 0:
            raise ValueError("skip must be >= 0")
        produced = 0

        for ranges, parts, sizes in self._blocks():
            assignments = 1
            for size in sizes:
                assignments *= size
            per_assignment = self._outputs_for(parts)
            if not assignments or not per_assignment:
                continue          # an empty tier set, or every slot in this block is empty

            block_total = assignments * per_assignment
            if skip >= block_total:
                skip -= block_total
                continue

            index = 0
            if skip:
                index, skip = divmod(skip, per_assignment)

            while index < assignments:
                values = self._assignment(ranges, sizes, index)
                index += 1
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
