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


class Consent(unittest.TestCase):
    """Nothing is measured until the visitor asks for it.

    Measuring a stranger's CPU the moment they open a page looks exactly like
    fingerprinting, whatever it actually does. The page waits to be asked, and explains
    itself when asked how.
    """

    def setUp(self):
        self.source = page_source()

    def test_nothing_runs_until_a_button_is_pressed(self):
        # every call site must be a handler the visitor triggers, never the page bootstrap
        code = re.sub(r"/\*.*?\*/", "", self.source, flags=re.S)      # drop comments
        code = re.sub(r"(?m)^\s*//.*$", "", code)
        sites = [m.start() for m in re.finditer(r"runBenchmark\s*\(", code)]
        stray = [p for p in sites
                 if not code[:p].rstrip().endswith("function")
                 and 'onclick="' not in code[max(0, p - 60):p]]
        self.assertTrue(sites, "the page no longer measures at all")
        self.assertFalse(stray,
                         "runBenchmark() runs {} time(s) outside a click handler; opening "
                         "the page must not start a measurement".format(len(stray)))

    def test_the_page_says_which_speed_it_is_using(self):
        # before measuring, the estimate comes from the reference machine and must say so
        self.assertIn("기준 컴퓨터", self.source)

    def test_nothing_claims_the_measurement_already_happened(self):
        # the footer used to open "computed from the speed measured on this computer",
        # which was true when the benchmark ran on load and became a lie the moment it
        # was put behind a button. Anything stated unconditionally has to hold before
        # anyone presses anything.
        foot = self.source.split('<p class="foot">')[1].split("</p>")[0]
        self.assertNotIn("이 컴퓨터에서 직접 잰", foot)
        self.assertIn("버튼을 눌러", foot)

    def test_measuring_is_offered_as_narrowing_not_as_exactness(self):
        # measuring replaces one machine's speed with another's. The parallel-scaling and
        # address-derivation figures stay borrowed either way, so the estimate gets better
        # rather than becoming correct, and the button should not promise otherwise.
        button = self.source.split('class="measure-btn" onclick="runBenchmark()"')[1] \
                            .split("</button>")[0]
        self.assertNotIn("정확하게", button)
        self.assertNotIn("정확히", button)

    def test_there_is_a_way_to_read_how_it_works(self):
        self.assertIn('id="howmodal"', self.source)
        self.assertIn("openModal", self.source)
        for promised in ("PBKDF2-HMAC-SHA512", "hardwareConcurrency",
                         "connect-src", "crypto.subtle"):
            self.assertIn(promised, self.source.split('id="howmodal"')[1])

    def test_the_modal_can_be_dismissed(self):
        modal = self.source.split('id="howmodal"')[1].split("<script>")[0]
        self.assertIn("modal-close", modal)
        self.assertIn("Escape", self.source)
        self.assertIn("closeAllModals", self.source)

    def test_nothing_about_the_visitor_is_kept(self):
        # a measurement that survives a reload is a stored fact about someone's machine
        for storage in ("localStorage", "sessionStorage", "document.cookie", "indexedDB"):
            self.assertNotIn(storage, self.source)


class PathDerivation(unittest.TestCase):
    """The page decides the derivation path from the address. So does the program.

    They must decide the same thing. If the page tells a customer their bc1q address means
    BIP84 and the program looks somewhere else, the search runs to the end and finds
    nothing -- and there is no error to notice, only a bill for a search that never had a
    chance. This runs both classifiers over the same addresses and compares.
    """

    # Real addresses, one of each type the page claims to recognise.
    ADDRESSES = {
        "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2":                          "p2pkh",
        "12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu":                          "p2pkh",
        "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy":                          "p2sh",
        "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4":                  "p2wpkh",
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr": "p2tr",
    }

    # The purposes those types imply, which is what a path is built from.
    PURPOSES = {"p2pkh": 44, "p2sh": 49, "p2wpkh": 84, "p2tr": 86}

    def setUp(self):
        self.source = page_source()

    def page_rules(self):
        """The page's addressKind() as (compiled pattern, kind) pairs, in order."""
        body = self.source.split("function addressKind(addr){")[1].split("\n}")[0]
        rules = []
        for pattern, flags, kind in re.findall(
                r"/\^([^/]+)/(i?)\.test\(a\)\)\s*return\s*\"(\w+)\"", body):
            rules.append((re.compile("^" + pattern, re.I if flags else 0), kind))
        self.assertTrue(rules, "addressKind() no longer reads as a list of prefix rules")
        return rules

    def page_kind(self, address):
        """What addressKind() returns, including its bech32 witness-version branch."""
        a = address.strip()
        if re.match(r"^(bc1|tb1)", a, re.I):
            witver = a.lower()[3:4]
            if witver == "p":
                return "p2tr"
            if witver == "q":
                threshold = int(re.search(r"a\.length\s*>\s*(\d+)", self.source).group(1))
                return "p2wsh" if len(a) > threshold else "p2wpkh"
            return None
        for pattern, kind in self.page_rules():
            if pattern.match(a):
                return kind
        return None

    def test_the_page_agrees_with_the_program(self):
        from btcrecover.btcrseed import WalletBIP32
        classify = WalletBIP32._classify_address_script_type
        for address, expected in self.ADDRESSES.items():
            with self.subTest(address=address):
                by_program = classify(None, address)
                self.assertEqual(by_program, expected,
                                 "the program's own classifier changed")
                self.assertEqual(self.page_kind(address), by_program,
                                 "page says {}, program says {}"
                                 .format(self.page_kind(address), by_program))

    def test_a_multisig_address_is_named_rather_than_guessed_at(self):
        """The one case where the page must know more than the program.

        A P2WSH address is bech32 witness v0 with a 32-byte program -- 62 characters where
        a single-signature bc1q address is 42. It is how native segwit multisig is held.
        The program returns None for it, does not filter any derivation path, and searches
        to the end without finding anything: no error, just a search that never had a
        chance. Matching on the bc1q prefix alone calls it BIP84, which is worse than
        saying nothing, so the page reads the length and says what it is.
        """
        from btcrecover.btcrseed import WalletBIP32
        p2wsh = "bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"
        self.assertEqual(len(p2wsh), 62)
        self.assertIsNone(WalletBIP32._classify_address_script_type(None, p2wsh),
                          "the program now classifies P2WSH; the page should too")

        kind = self.page_kind(p2wsh)
        self.assertIsNotNone(kind, "the page no longer recognises a P2WSH address")
        self.assertNotIn(kind, self.PURPOSES,
                         "P2WSH was given a single-key purpose; no passphrase reaches it")
        unsupported = self.source.split("const UNSUPPORTED = {")[1].split("}")[0]
        self.assertIn(kind, unsupported)

    def test_taproot_is_not_mistaken_for_multisig(self):
        # P2TR is also 62 characters, so a rule that went by length alone would refuse a
        # wallet it can actually recover
        p2tr = "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr"
        self.assertEqual(len(p2tr), 62)
        self.assertEqual(self.page_kind(p2tr), "p2tr")

    def test_the_customer_is_told_before_they_pay(self):
        # the failure this prevents is a bill for a search that could not have worked
        for said in ("멀티시그", "공동서명", "찾지 못합니다"):
            self.assertIn(said, self.source)

    def test_p2sh_ambiguity_is_admitted(self):
        # a 3... address is identical whether it is single-signature or multisig; the page
        # must not imply it checked
        self.assertIn('kind === "p2sh"', self.source)

    def test_every_kind_maps_to_a_purpose(self):
        purposes = dict(re.findall(r"(\w+):\s*(\d+)",
                                   self.source.split("const PURPOSE = {")[1].split("}")[0]))
        self.assertEqual({k: int(v) for k, v in purposes.items()}, self.PURPOSES)

    def test_an_unrecognised_address_is_not_silently_narrowed(self):
        # guessing one path for an address nobody understood would search the wrong tree
        # in silence; trying the common four at least can succeed
        self.assertIsNone(self.page_kind("not-an-address"))
        derived = self.source.split("function derivationPaths(){")[1].split("\n}")[0]
        self.assertIn("[44, 49, 84, 86]", derived)

    def test_the_path_is_not_something_the_customer_picks(self):
        # a dropdown of purposes asks a question the address already answered, and a wrong
        # answer loses the recovery
        self.assertNotIn('<select id="paths">', self.source)
        self.assertIn('id="accounts"', self.source)      # what the address cannot say
        self.assertIn('id="changechain"', self.source)


class AfterRecovery(unittest.TestCase):
    """What to do once the passphrase is found, said in both places that say it.

    The program says this on its success screen, which is too late to order a hardware
    wallet. The page has to say it too, before anyone starts. And the two must not drift
    apart: a customer who reads one and follows the other should not end up somewhere
    different.
    """

    # The claims that carry the security, in whatever wording each surface uses.
    CLAIMS = [
        ("계속 오프라인", "the recovery machine is not reconnected to move the funds"),
        ("하드웨어 지갑", "the seed is restored onto a device, not a networked wallet"),
        ("서명은 하드웨어 지갑 안에서", "the key never reaches the broadcasting device"),
        ("한 번에", "one hop, no stop at a hot wallet on the way"),
        ("하드웨어 지갑 화면에서 직접 확인", "the receiving address is checked on the device"),
        ("하드웨어 지갑이 없다면", "someone without one still has something to do today"),
    ]

    @staticmethod
    def flat(text):
        """Both surfaces wrap their sentences across source lines wherever they like."""
        return re.sub(r"\s+", " ", text.replace("\\n", " "))

    def setUp(self):
        self.page = page_source()
        gui = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "recovery_gui.py")
        with open(gui, "r", encoding="utf-8") as f:
            self.gui = f.read()

    def modal(self):
        return self.flat(self.page.split('id="aftermodal"')[1].split('id="howmodal"')[0])

    def test_the_page_says_it_before_anyone_starts(self):
        self.assertIn('id="aftermodal"', self.page)
        modal = self.modal()
        for claim, why in self.CLAIMS:
            with self.subTest(why):
                self.assertIn(claim, modal)

    def test_the_program_says_the_same_thing(self):
        gui = self.flat(self.gui)
        for claim, why in self.CLAIMS:
            with self.subTest(why):
                self.assertIn(claim, gui)

    def test_the_page_tells_them_in_time_to_buy_one(self):
        # a hardware wallet ordered after the passphrase is found arrives days late, and
        # the risk runs the whole time
        self.assertIn("지금 주문", self.modal())

    def test_neither_surface_calls_offline_a_proof(self):
        # offline running is prevention, not evidence -- claiming otherwise costs the
        # credibility of the parts that can actually be checked
        modal = self.modal()
        self.assertIn("증명은 아닙니다", modal)
        for surface in (modal, self.flat(self.gui)):
            self.assertNotIn("완전히 안전합니다", surface)

    def test_the_link_is_where_they_commit(self):
        # next to the download, which is the moment they decide to go ahead
        export = self.page.split("<h2>내보내기</h2>")[1].split("</div>\n  </div>")[0]
        self.assertIn("openModal('aftermodal')", export)


if __name__ == '__main__':
    unittest.main()
