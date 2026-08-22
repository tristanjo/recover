#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_ci_test_step.py -- unit tests for the CI step that runs this fork's suites
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

"""The Windows job once reported success while a suite was red, and shipped twice.

The step listed the suites one `python -m unittest` per line. The runner's shell keeps
going after a failing line and exits with the *last* line's status, so every failure but
the last was thrown away -- test_cjk_passphrase was broken on Windows through v0.1.5 and
v0.1.6 without anything turning red.

These pin the replacement: every suite runs, every failure counts, and the step calls the
runner rather than growing a list of lines again.
"""

import contextlib
import importlib.util
import io
import os
import sys
import unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RUNNER = os.path.join(ROOT, ".github", "run_fork_tests.py")
WORKFLOWS = (os.path.join(ROOT, ".github", "workflows", "build-windows.yml"),
             os.path.join(ROOT, ".github", "workflows", "build-macos.yml"))


def load_runner():
    spec = importlib.util.spec_from_file_location("run_fork_tests", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStep(unittest.TestCase):

    def setUp(self):
        self.runner = load_runner()

    def test_every_suite_this_fork_added_is_run(self):
        here = os.path.dirname(__file__)
        mine = {"test_passphrase_grammar", "test_cjk_passphrase", "test_hangul_keys",
                "test_embed", "test_recovery_gui", "test_ci_test_step"}
        for name in sorted(mine):
            self.assertTrue(os.path.exists(os.path.join(here, name + ".py")),
                            name + " is listed but no longer exists")
            self.assertIn("btcrecover.test." + name, self.runner.MODULES,
                          name + " exists but nothing runs it")

    def test_a_failure_anywhere_fails_the_step(self):
        """Not only the last one. That is the bug that shipped twice."""
        for position in range(len(self.runner.MODULES)):
            with self.subTest(position=position):
                seen = []

                def run(module, position=position):
                    seen.append(module)
                    failing = self.runner.MODULES[position]
                    return (1 if module == failing else 0), "FAIL: pretend\nRan 1 test"

                self.runner.run = run
                with contextlib.redirect_stdout(io.StringIO()):  # it narrates; not here
                    verdict = self.runner.main()
                self.assertEqual(verdict, 1,
                                 "a failure at position %d was thrown away" % position)
                self.assertEqual(seen, list(self.runner.MODULES),
                                 "stopped early, so later suites went unrun")

    def test_a_clean_run_passes(self):
        self.runner.run = lambda module: (0, "Ran 1 test\nOK")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.runner.main(), 0)

    def test_the_annotation_names_the_test_and_not_the_exit_code(self):
        output = ('FAIL: test_something (a.b.C.test_something)\n'
                  '  File "D:\\a\\x.py", line 61, in test_something\n'
                  '    self.assertEqual(1, 2)\n'
                  'AssertionError: 1 != 2\n'
                  'Ran 10 tests in 0.001s\n'
                  'FAILED (failures=1)\n')
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.runner.annotate("a.b", output)
        line = printed.getvalue().strip()
        self.assertTrue(line.startswith("::error title=a.b::"))
        self.assertEqual(line.count("\n"), 0, "a newline would cut the annotation short")
        for wanted in ("test_something", "line 61", "AssertionError: 1 != 2", "Ran 10 tests"):
            self.assertIn(wanted, line, "the annotation dropped " + wanted)

    def test_the_runner_survives_a_cp1252_stdout(self):
        """It relays Korean test output, so its own stdout has to be able to carry it.

        Found by running the whole set under PYTHONIOENCODING=cp1252: the script died
        relaying the second suite, which would have thrown away everything after the
        first -- the same shape of hole this file exists to close.
        """
        class Stream:
            def __init__(self):
                self.asked = []

            def reconfigure(self, **kw):
                self.asked.append(kw)

        out, err = Stream(), Stream()
        original = self.runner.sys.stdout, self.runner.sys.stderr
        self.runner.sys.stdout, self.runner.sys.stderr = out, err
        try:
            self.runner.speak_utf8()
        finally:
            self.runner.sys.stdout, self.runner.sys.stderr = original
        for stream in (out, err):
            self.assertEqual(stream.asked, [{"encoding": "utf-8", "errors": "replace"}])

    def test_the_step_repairs_its_stdout_before_running_anything(self):
        order = []
        self.runner.speak_utf8 = lambda: order.append("repaired")
        self.runner.run = lambda module: (order.append(module), (0, "OK"))[1]
        with contextlib.redirect_stdout(io.StringIO()):
            self.runner.main()
        self.assertEqual(order[0], "repaired", "ran a suite before stdout could carry it")

    def test_the_workflows_call_the_runner_rather_than_listing_lines(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=os.path.basename(path)):
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read()
                self.assertIn("python .github/run_fork_tests.py", text)
                for line in text.splitlines():
                    self.assertNotIn("python -m unittest", line,
                                     "back to one line per suite, where all but the last "
                                     "failure is thrown away")


if __name__ == '__main__':
    unittest.main()
