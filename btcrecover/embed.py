#!/usr/bin/env python
# -*- coding: utf-8 -*-

# embed.py -- run a passphrase search from inside an application
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

"""Runs a passphrase search from a config.json, in this process.

The command line entry points assume a terminal: they print, they read argv, and they
call sys.exit on anything unexpected. A GUI needs none of that -- it needs progress it
can draw, a stop button that works, and a result it can branch on. This module supplies
those without a subprocess, feeding the grammar to btcrpass directly as `base_iterator`
so no candidate is ever written to disk or to a pipe.

    from btcrecover import embed

    plan = embed.SearchPlan.from_file("config.json")
    result = embed.run(plan, mnemonic, progress=on_progress, abort=stop_event)
    if result.found:
        print(result.passphrase, result.normalization)

The mnemonic is a parameter and never comes from the config: the config is written on a
website, and a seed phrase must not be.
"""

import contextlib, io, json, multiprocessing, os, sys, threading, time

from btcrecover.passphrase_grammar import PassphraseGrammar, GrammarError

__all__ = ["SearchPlan", "SearchResult", "run", "prepare_frozen_start"]

DEFAULT_ADDRESS_LIMIT = 10
DEFAULT_PATHS = ["m/44'/0'/0'/0", "m/49'/0'/0'/0", "m/84'/0'/0'/0"]


def prepare_frozen_start():
    """Must be the first thing a frozen executable does, before any other work.

    Windows has no fork, so every worker process starts by re-running the executable.
    Unfrozen that is harmless -- the `if __name__ == "__main__"` guard stops the child
    before it repeats the program. A PyInstaller build has no such guard to reach, so
    without this call each worker launches its own workers, and the machine fills up
    with processes within seconds.

    Worker processes re-enter here too, which is why the stream repair below belongs
    in front of freeze_support() rather than after it.
    """
    _ensure_streams()
    multiprocessing.freeze_support()


def _ensure_streams():
    """Give print() somewhere to go, and something it is able to encode.

    Two ways this breaks, both of which strike at the worst possible moment -- when a
    match is found and BTCRecover prints it from a worker process.

    A windowed PyInstaller executable leaves sys.stdout and sys.stderr as None, and any
    print() then raises.

    A Windows console encodes as cp1252, in which Hangul has no representation at all.
    A recovered seed phrase from the Korean wordlist, or any Korean message, raises
    UnicodeEncodeError on its first character.
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
        elif hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError, LookupError):
                try:
                    # UTF-8 refused; at least stop an unencodable character from raising
                    stream.reconfigure(errors="replace")
                except (OSError, ValueError):
                    pass


class SearchPlan:
    """Everything from config.json that the search needs -- and nothing about the seed."""

    def __init__(self, config):
        if not isinstance(config, dict):
            raise GrammarError("config must be a JSON object")
        wallet = config.get("wallet") or {}

        self.grammar = PassphraseGrammar(config)
        self.wallet_type = str(wallet.get("type") or "bip39").lower()
        self.addresses = [a for a in (wallet.get("addresses") or []) if a]
        self.address_limit = int(wallet.get("address_limit") or DEFAULT_ADDRESS_LIMIT)

        paths = wallet.get("derivation_paths") or DEFAULT_PATHS
        if isinstance(paths, str):     # tolerate a single path written as a bare string
            paths = [paths]
        self.derivation_paths = [str(p) for p in paths if p]

        self.normalizations = list(self.grammar.normalizations)
        self.language = wallet.get("language")

        if not self.addresses:
            raise GrammarError("config lists no wallet address; without one there is "
                               "nothing to recognise the right passphrase by")

    @classmethod
    def from_file(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return cls(json.load(f))
            except json.JSONDecodeError as e:
                raise GrammarError("{} is not valid JSON: {}".format(path, e))

    def candidate_count(self):
        return self.grammar.count()

    def _argv(self, mnemonic, threads=None):
        argv = [
            "--wallet-type", self.wallet_type,
            "--mnemonic", mnemonic,
            "--addrs", *self.addresses,
            "--addr-limit", str(self.address_limit),
            "--bip32-path", *self.derivation_paths,
            "--passphrase-normalizations", ",".join(self.normalizations),
            # The count is already known exactly, so let btcrpass skip its counting pass;
            # a pass over a hundred million candidates just to draw a bar is not worth it.
            "--no-eta",
            "--no-dupchecks",
            "--dsw",             # the host is responsible for its own security notices
            "--skip-pre-start",
        ]
        if self.language:
            argv += ["--language", self.language]
        if threads:
            argv += ["--threads", str(threads)]
        return argv


class SearchResult:
    """What happened. Exactly one of `found`, `aborted` and `error` is meaningful."""

    def __init__(self, found=False, passphrase=None, normalization=None,
                 tried=0, elapsed=0.0, aborted=False, error=None, log=""):
        self.found = found
        self.passphrase = passphrase
        self.normalization = normalization
        self.tried = tried
        self.elapsed = elapsed
        self.aborted = aborted
        self.error = error
        self.log = log

    def __repr__(self):
        if self.error:   state = "error: " + self.error
        elif self.aborted: state = "aborted"
        elif self.found: state = "found " + repr(self.passphrase)
        else:            state = "not found"
        return "<SearchResult {} after {:,} in {:.1f}s>".format(state, self.tried, self.elapsed)


def run(plan, mnemonic, progress=None, abort=None, threads=None, skip=0):
    """Search for the passphrase. Blocks until it finds one, runs out, or is aborted.

    `progress` is called as progress(tried, total) from the search thread, often -- keep
    it cheap and marshal to the UI thread yourself. `abort` is a threading.Event; setting
    it stops the search between chunks. `skip` resumes a previous run.

    btcrpass keeps its configuration in module globals, so only one search may be in
    flight per process; `run` enforces that rather than letting two corrupt each other.
    """
    from btcrecover import btcrpass

    if not mnemonic or not mnemonic.strip():
        return SearchResult(error="no mnemonic was entered")

    total = plan.candidate_count()
    remaining = max(0, total - skip)
    if not remaining:
        return SearchResult(tried=0, error="nothing left to search: skip is past the end")

    def candidates():
        return plan.grammar.generate(skip=skip)

    captured = io.StringIO()
    started = time.monotonic()
    tried_holder = [0]

    def on_progress(tried, _unused_total):
        tried_holder[0] = tried
        if progress:
            progress(tried, remaining)

    _share_tk_root()

    with _search_lock:
        btcrpass.progress_hook = on_progress
        btcrpass.abort_event = abort
        try:
            # btcrpass narrates to stdout throughout; a GUI wants that as text it can show
            # on demand, not interleaved with whatever else the process is printing.
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                btcrpass.parse_arguments(plan._argv(mnemonic, threads), base_iterator=candidates)
                password_found, not_found_msg = btcrpass.main()
        except SystemExit as e:
            # error_exit() is how btcrpass reports bad input; in a terminal that is a
            # clean exit, here it is just a message to put in front of the user.
            return SearchResult(tried=tried_holder[0], elapsed=time.monotonic() - started,
                                error=_clean_exit_message(e), log=captured.getvalue())
        except (GrammarError, ValueError, OSError) as e:
            return SearchResult(tried=tried_holder[0], elapsed=time.monotonic() - started,
                                error=str(e), log=captured.getvalue())
        finally:
            btcrpass.progress_hook = None
            btcrpass.abort_event = None

    log = captured.getvalue()
    elapsed = time.monotonic() - started
    tried = tried_holder[0]

    if isinstance(password_found, str):
        return SearchResult(found=True, passphrase=password_found,
                            normalization=_normalization_of(btcrpass, password_found),
                            tried=tried, elapsed=elapsed, log=log)
    if abort is not None and abort.is_set():
        return SearchResult(tried=tried, elapsed=elapsed, aborted=True, log=log)
    return SearchResult(tried=remaining, elapsed=elapsed, log=log)


_search_lock = threading.Lock()


def _clean_exit_message(exc):
    message = str(exc.code) if exc.code not in (None, 0) else "search exited early"
    return message.replace("Error: ", "").strip() or "search exited early"


def _share_tk_root():
    """Lend btcrseed the host's Tk root so it never builds a second one.

    A process may hold only one Tk instance; creating a second after the first exists
    segfaults on macOS rather than raising. btcrseed builds its own root when a required
    input is missing and it has to ask the user. A SearchPlan supplies all three of those
    inputs, so this should be unreachable -- but the failure it prevents would take a
    running recovery down with it, which is too expensive to leave to "should".
    """
    try:
        import tkinter
    except ImportError:
        return
    root = getattr(tkinter, "_default_root", None)
    if root is None:
        return
    from btcrecover import btcrseed
    if not btcrseed.tk_root:
        btcrseed.tk_root = root


def _normalization_of(btcrpass, passphrase):
    """Which Unicode form matched.

    The worker process that found it printed the form to its own stdout, which this
    process never sees, so ask the wallet again here. NFC and NFD are the same glyphs on
    screen, and a user re-entering the passphrase elsewhere has to know which it was.
    """
    wallet = getattr(btcrpass, "loaded_wallet", None)
    if wallet is None or not hasattr(wallet, "normalization_of"):
        return None
    try:
        return wallet.normalization_of(passphrase)
    except Exception:
        return None      # a label for the user is never worth failing a recovery over
