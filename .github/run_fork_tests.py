#!/usr/bin/env python3
"""Run the suites this fork adds, and say what broke somewhere readable.

A Windows-only failure once cost three wrong guesses, because the log needs credentials
to read and the annotation the runner produced said only "Process completed with exit
code 1". Annotations are served by the public REST API, so this re-emits the lines that
name the failure as ``::error::`` -- and the next failure can be read without an account.

Each module runs in its own process: test_seeds and test_passwords share global state in
btcrpass and cannot be collected together, which is how run-all-tests.py does it too.
"""

import os
import re
import subprocess
import sys

MODULES = (
    "btcrecover.test.test_passphrase_grammar",
    "btcrecover.test.test_cjk_passphrase",
    "btcrecover.test.test_hangul_keys",
    "btcrecover.test.test_embed",
    "btcrecover.test.test_recovery_gui",
)

# The verdict lines, the test that produced them, and the frames in between.
NAMES = re.compile(r'^(FAIL|ERROR|OK|Ran \d|FAILED|\s+File ")|Error:|assert')

# Annotations are one line; a newline would cut the message short.
JOIN = "  //  "
LIMIT = 4000


def run(module):
    print("$ python -m unittest -v " + module, flush=True)
    done = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", module],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # Windows consoles are not UTF-8 by default and these suites print Korean.
        encoding="utf-8", errors="replace",
    )
    print(done.stdout, flush=True)
    return done.returncode, done.stdout


def annotate(module, output):
    named = [line.strip() for line in output.splitlines() if NAMES.search(line)]
    message = JOIN.join(named)[:LIMIT] or "no line named the failure; read the log"
    # ::error:: needs its own line, and GitHub reads it from stdout.
    print("::error title=%s::%s" % (module, message), flush=True)


def main():
    broke = []
    for module in MODULES:
        code, output = run(module)
        if code != 0:
            broke.append(module)
            if os.environ.get("GITHUB_ACTIONS"):
                annotate(module, output)
            else:
                print("would annotate: ", end="")
                annotate(module, output)
    if broke:
        print("failed: " + ", ".join(broke), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
