#!/usr/bin/env python
# -*- coding: utf-8 -*-

# passphrase_rank_benchmark.py -- how early does the grammar reach the right answer?
# Copyright (C) 2026 tristanjo
#
# This file is part of btcrecover, distributed under the GNU GPL v2 or later.

"""Measures where the true passphrase lands in the order the grammar produces.

The point of priority ordering is to reach the answer sooner. Without a number for
"sooner", any change to the model is an assertion: it looks more principled, so it must be
better. This turns that into an experiment -- change the model, run this, see whether the
answers moved forward.

    python utilities/passphrase_rank_benchmark.py
    python utilities/passphrase_rank_benchmark.py --cap 5000000

The cases are hand-written, and that is the honest limit of this tool. They encode what I
think passphrase construction looks like, so a model tuned until this number is beautiful
has been tuned to my guesses. It is sound for two narrower purposes: catching a change that
makes things worse, and comparing two models on the same fixed set. Replace the cases with
real ones as soon as there are real ones.
"""

import argparse, os, statistics, sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from btcrecover.passphrase_grammar import PassphraseGrammar


def words(candidates, cases=("asis",), **kwds):
    return dict(type="words", candidates=list(candidates), cases=list(cases), **kwds)

def digits(lo, hi, **kwds):
    return dict(type="digits", length=[lo, hi], **kwds)

def symbols(candidates, **kwds):
    return dict(type="symbols", candidates=list(candidates), **kwds)

def pool(candidates, choose, **kwds):
    return dict(type="pool", candidates=list(candidates), choose=list(choose), **kwds)


# (name, slots, separators, permute, the passphrase that was actually used)
#
# Each is a grammar the interview could plausibly have produced, paired with an answer
# inside it. Where a case exists to test one thing, the rest is kept small so the number
# reflects that thing.
CASES = [
    ("word + wedding year",        [words(["minji"]), digits(4, 4)], [""], False, "minji2014"),
    ("word + birth year",          [words(["minji"]), digits(4, 4)], [""], False, "minji1988"),
    ("word + old birth year",      [words(["minji"]), digits(4, 4)], [""], False, "minji1961"),
    ("word + a date, not a year",  [words(["minji"]), digits(4, 4)], [""], False, "minji0301"),
    ("word + 1234",                [words(["minji"]), digits(4, 4)], [""], False, "minji1234"),
    ("word + two digits",          [words(["minji"]), digits(2, 2)], [""], False, "minji88"),
    ("word + digits, length unsure", [words(["minji"]), digits(2, 4)], [""], False, "minji2014"),
    ("second of two words",        [words(["minji", "sarang"]), digits(4, 4)], [""], False, "sarang2014"),
    ("third of three words",       [words(["a", "b", "minji"]), digits(4, 4)], [""], False, "minji2014"),
    ("capitalised word",           [words(["minji"], ["asis", "lower", "title", "upper"]), digits(4, 4)],
                                   [""], False, "Minji2014"),
    ("word + year + symbol",       [words(["minji"]), digits(4, 4), symbols(["!", "@", "#"])],
                                   [""], False, "minji2014!"),
    ("hyphen separator",           [words(["minji"]), digits(4, 4)], ["", "-", "_"], False, "minji-2014"),
    ("digits first",               [words(["minji"]), digits(4, 4)], [""], True, "2014minji"),
    ("Korean word + year",         [words(["비밀번호"]), digits(4, 4)], [""], False, "비밀번호2024"),
    ("two of four words",          [pool(["민지", "사랑", "2014", "우리집"], [2, 3])], [""], False, "사랑2014"),
    ("word + long digits",         [words(["minji"]), digits(6, 6)], [""], False, "minji112233"),
    # Six digits are a birthday far more often than anything else here -- it is how a Korean
    # ID number starts. These two are the pair that shows both sides of that bet: what the
    # date tier buys, and what it costs the runs that are not dates.
    ("word + birthday YYMMDD",     [words(["minji"]), digits(6, 6)], [""], False, "minji880301"),
    ("word + recent YYMMDD",       [words(["minji"]), digits(6, 6)], [""], False, "minji011225"),
    ("word + six random digits",   [words(["minji"]), digits(6, 6)], [""], False, "minji473916"),
]


def rank_of(spec, answer, cap):
    """Position of `answer` in the order this grammar produces, 1-based; None past `cap`."""
    grammar = PassphraseGrammar(spec)
    for position, candidate in enumerate(grammar.generate(limit=cap), 1):
        if candidate == answer:
            return position, grammar.count()
    return None, grammar.count()


def run(cap):
    rows, fractions = [], {True: [], False: []}
    for name, slots, separators, permute, answer in CASES:
        row = {"name": name, "answer": answer}
        for priority in (False, True):
            spec = {"passphrase": {"slots": slots, "separators": separators,
                                   "permute_order": permute, "priority": priority}}
            position, total = rank_of(spec, answer, cap)
            row["total"] = total
            row["on" if priority else "off"] = position
            if position:
                fractions[priority].append(position / total)
        rows.append(row)

    width = max(len(r["name"]) for r in rows)
    print(f"{'case':<{width}} {'space':>12} {'plain':>10} {'priority':>10} {'change':>9}")
    print("-" * (width + 45))
    for r in rows:
        off, on = r["off"], r["on"]
        if off and on:
            ratio = off / on
            change = f"{ratio:,.1f}x" if ratio >= 1 else f"{1/ratio:,.1f}x 느림"
        else:
            change = "-"
        print(f"{r['name']:<{width}} {r['total']:>12,} "
              f"{(f'{off:,}' if off else '>cap'):>10} {(f'{on:,}' if on else '>cap'):>10} {change:>9}")

    print()
    for priority in (False, True):
        f = fractions[priority]
        if not f:
            continue
        label = "priority" if priority else "plain   "
        within = lambda p: sum(1 for x in f if x <= p)
        print(f"  {label}  중앙값 {statistics.median(f)*100:6.2f}% 지점   "
              f"상위 1% 안 {within(.01):>2}/{len(f)}   상위 10% 안 {within(.10):>2}/{len(f)}")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cap", type=int, default=2_000_000,
                        help="stop looking after this many candidates (default: 2,000,000)")
    run(parser.parse_args().cap)
