#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_webapp_model.py -- does the web page's time estimate match the program's real speed?
# Copyright (C) 2026 tristanjo
#
# This file is part of btcrecover, distributed under the GNU GPL v2 or later.

"""webapp/diagnostic.html quotes a customer how long their recovery will take, and that
quote is what they decide to pay on. The numbers behind it are measurements of this
program, but they live in JavaScript where no test could see them -- and they were wrong
by 37% for a while without anything noticing.

This reads the constants back out of the page and checks they still reproduce the runs
they were taken from. It is not a change detector: MEASURED below is the raw data, and a
change to the page is fine as long as it still predicts these.

Re-measure with (one thread, so the number is per core):

    python utilities/... -- see CHANGES.md for the harness used

If the program itself gets faster or slower, these numbers move and the page must move
with them. That is the point.
"""

import os, re, sys, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "webapp", "diagnostic.html")

# Measured on the reference machine (Apple Silicon, wallycore), one thread, 20,000
# candidates per point, one derivation path: address count -> microseconds per candidate.
MEASURED = {1: 645.0, 5: 817.7, 10: 1038.1, 20: 1432.9}

# Same machine, 150,000 candidates per point: thread count -> candidates per second.
# The size matters -- at 40,000 the pool startup is still a visible share of the run and
# the high end reads about 20% low.
MEASURED_SCALING = {1: 995.4, 2: 1961.9, 4: 3527.9, 8: 6367.4,
                    10: 7433.2, 12: 8654.1, 14: 9770.7}

TOLERANCE = 0.05


def page_source():
    with open(PAGE, "r", encoding="utf-8") as f:
        return f.read()


def constant(source, name):
    """The value of `name:` inside the REF object, which may be written 603.5e-6."""
    m = re.search(r"\b" + name + r":\s*([0-9.]+(?:e-?[0-9]+)?)", source)
    if not m:
        raise AssertionError("webapp/diagnostic.html no longer defines REF." + name)
    return float(m.group(1))


def scaling(source):
    m = re.search(r"scaling:\s*\[(.*?)\]\s*\n", source, re.S)
    if not m:
        raise AssertionError("webapp/diagnostic.html no longer defines REF.scaling")
    return {int(a): float(b) for a, b in re.findall(r"\[\s*([0-9]+)\s*,\s*([0-9.]+)\s*\]",
                                                    m.group(1))}


class CostModel(unittest.TestCase):

    def setUp(self):
        self.source = page_source()
        self.fixed = constant(self.source, "fixedSec")
        self.per_address = constant(self.source, "addrSec")

    def test_reproduces_every_measured_point(self):
        for addresses, micros in sorted(MEASURED.items()):
            with self.subTest(addresses=addresses):
                predicted = (self.fixed + addresses * self.per_address) * 1e6
                self.assertLess(abs(predicted - micros) / micros, TOLERANCE,
                                "{} addresses: page says {:.1f}us, measured {:.1f}us"
                                .format(addresses, predicted, micros))

    def test_the_fixed_cost_is_more_than_the_pbkdf2_it_contains(self):
        # 2048 rounds of PBKDF2-HMAC-SHA512 is 414us of the 603.5us; the rest is what it
        # costs to put one candidate through btcrpass. A model that forgot the remainder
        # would quote every customer a search 30% shorter than the one they get.
        pbkdf2 = 1.0 / constant(self.source, "pythonPerSec")
        self.assertGreater(self.fixed, pbkdf2 * 1.2)
        self.assertLess(self.fixed, pbkdf2 * 2.0)

    def test_paths_are_not_multiplied_into_the_cost(self):
        # Ten addresses over one path measured 1038.1us and over three paths 1045.1us --
        # btcrecover skips paths that do not match the address type, and says so in its
        # own log. The page must count matching paths, not chosen ones.
        self.assertIn("const pathCount = matchingPaths();", self.source)
        self.assertTrue(re.search(r"secPer\s*=\s*\(REF\.fixedSec\s*\+\s*pathCount\s*\*"
                                  r"\s*addrLimit\s*\*\s*REF\.addrSec\)", self.source),
                        "the per-candidate cost no longer reads as fixed + paths x addresses")


class Scaling(unittest.TestCase):

    def setUp(self):
        self.curve = scaling(page_source())

    def test_matches_the_measured_thread_counts(self):
        base = MEASURED_SCALING[1]
        for threads, rate in sorted(MEASURED_SCALING.items()):
            with self.subTest(threads=threads):
                self.assertIn(threads, self.curve)
                measured = rate / base
                self.assertLess(abs(self.curve[threads] - measured) / measured, TOLERANCE,
                                "{} threads: page says {:.2f}x, measured {:.2f}x"
                                .format(threads, self.curve[threads], measured))

    def test_more_cores_never_means_less_work(self):
        counts = sorted(self.curve)
        for a, b in zip(counts, counts[1:]):
            self.assertGreater(self.curve[b], self.curve[a])

    def test_no_core_count_is_credited_with_more_than_itself(self):
        # the failure that matters: a curve above the diagonal quotes a time nobody can hit
        for threads, factor in self.curve.items():
            self.assertLessEqual(factor, threads)


class Measurement(unittest.TestCase):
    """The page measures the visitor's machine rather than assuming one."""

    def setUp(self):
        self.source = page_source()

    def test_it_measures_rather_than_asks(self):
        self.assertIn("crypto.subtle", self.source)
        self.assertIn("PBKDF2", self.source)
        self.assertIn("SHA-512", self.source)
        self.assertIn("2048", self.source)

    def test_the_calibration_is_taken_the_same_way_it_is_used(self):
        # browserPerSec must come from the same statistic measureThisMachine() computes.
        # Measured by average it is 2,193/s and by the 20% quantile 2,500/s; using the
        # average as the calibration for a quantile measurement inflates every estimate
        # by 14%.
        self.assertAlmostEqual(constant(self.source, "browserPerSec"), 2500, delta=1)
        self.assertIn("0.2", self.source)

    def test_an_implausible_measurement_is_refused(self):
        # a benchmark that can be starved gives 0.86/s instead of 2,414/s, and a page that
        # believed it would quote centuries. Both guards have to stay.
        self.assertIn("PLAUSIBLE", self.source)
        self.assertIn("requestIdleCallback", self.source)

    def test_measuring_costs_no_network_request(self):
        # the whole argument for the page is that it never connects anywhere, so the
        # benchmark must not have reached for anything remote to do its work
        bench = self.source.split("async function measureThisMachine")[1].split("\n}")[0]
        for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "import(", "src="):
            self.assertNotIn(forbidden, bench)


if __name__ == '__main__':
    unittest.main()
