# -*- mode: python ; coding: utf-8 -*-

# recovery_gui.spec -- PyInstaller build for the offline recovery window
# Copyright (C) 2026 tristanjo
#
# This file is part of btcrecover, distributed under the GNU GPL v2 or later.
#
# Built as a folder rather than a single file, on purpose. A one-file build unpacks
# itself to a temporary directory at every launch, which is both the shape antivirus
# heuristics dislike most and the shape that hides what shipped. A folder can be looked
# through, and its contents diffed against a build made from the same source.
#
#   pyinstaller recovery_gui.spec
#
# Set BTCR_GUI_CONSOLE=1 to keep a console window attached, which is the only way to see
# an early crash. Without it the build is windowed, and the workers' output goes nowhere
# -- see embed.prepare_frozen_start() for why that has to be survivable.

import os

CONSOLE = os.environ.get("BTCR_GUI_CONSOLE") == "1"

a = Analysis(
    ["recovery_gui.py"],
    pathex=[],
    binaries=[],
    # btcrseed resolves these relative to its own __file__, which inside a bundle points
    # at the extracted tree -- so the layout has to be preserved, not flattened.
    datas=[("btcrecover/wordlists", "btcrecover/wordlists"),
           # bitcoinlib reads these at import time and refuses to load without them
           ("lib/bitcoinlib/config", "lib/bitcoinlib/config"),
           ("lib/bitcoinlib/data", "lib/bitcoinlib/data"),
           ("lib/bitcoinlib/wordlist", "lib/bitcoinlib/wordlist"),
           # GPLv2 obliges us to ship these alongside the binary, and they are also the
           # first thing anyone auditing the folder should be able to find
           ("LICENSE.txt", "."),
           ("CHANGES.md", ".")],
    hiddenimports=[
        # wallycore is a SWIG wrapper: it reaches its native library through
        # importlib.import_module("_wallycore"), which static analysis cannot see. Miss
        # it and the build silently falls back to the pure-Python secp256k1, which is
        # correct and roughly two orders of magnitude slower.
        "_wallycore", "wallycore",
        # the alternative C backend, used on Python versions that have a wheel for it
        "coincurve",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here is reachable from the recovery window, and every megabyte left in is
    # another megabyte someone has to account for when asking why they should trust this.
    excludes=[
        "pyopencl", "numpy", "matplotlib", "scipy", "pandas",
        "IPython", "pytest", "setuptools", "pip",
        "PIL", "PyQt5", "PyQt6", "PySide2", "PySide6",
        "green", "argcomplete",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="passphrase-recovery",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX packing is a strong antivirus false-positive trigger
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="passphrase-recovery",
)
