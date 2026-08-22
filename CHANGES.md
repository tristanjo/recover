# Changes in this fork

This repository is a fork of [3rdIteration/btcrecover](https://github.com/3rdIteration/btcrecover),
maintained by Stephen Rothery, which is itself a continuation of the original *btcrecover* by
Christopher Gurnee. All of their work remains under their copyright.

Like the upstream project, this fork is distributed under the **GNU General Public License, version 2
or (at your option) any later version** — see [LICENSE.txt](LICENSE.txt). That means anyone who
receives this software, in source or binary form, is free to read it, modify it, and redistribute it,
and is entitled to the complete corresponding source code.

GPLv2 section 2(a) requires modified files to carry a notice of the change and its date. Each file
changed here carries such a notice in its header, and the changes are summarized below.

The first commit in this repository is an unmodified snapshot of upstream, so everything this fork
changed is exactly `git diff <that commit> HEAD` — no summary here can drift away from the code.

---

## 2026-08-22 — Build for macOS as well

**Changed:** `recovery_gui.spec`, `.github/workflows/build-macos.yml` (new),
`.github/workflows/build-windows.yml`, `docs/Verifying_The_Download.md` (new)

macOS will not launch a bare folder as an application, so the same collected tree is now
also wrapped in a `.app` and shipped as a `.dmg`. The folder is still produced beside it and
still diffable; the bundle only adds what Finder needs. Built and self-tested locally before
being wired into CI: the `.app` passes, the `.dmg` mounts, and the app inside it passes —
`TREZOR` recovered from the published BIP39 vector in 2.7 seconds on the wallycore backend.

Both architectures are built. Rosetta would run an Intel binary on Apple Silicon, but at a
fraction of the speed, on a job whose entire cost is speed — and a customer who downloads
the wrong one gets a program that will not start and no explanation.

The first attempt named `macos-13` for Intel, which was retired in December 2025. The job
did not fail: it queued for forty minutes for a machine that was never coming, while the
Windows job on the same commit finished in two. A workflow can be wrong in a way that
produces no error at all, and a `timeout-minutes` does not help because the clock starts
when a job begins, not when it is queued. Now `macos-15` and `macos-15-intel` — the latter
being the last x86_64 image Actions will offer, retiring August 2027, which is recorded in
the workflow so it is not discovered the same way.

**Gatekeeper is the real obstacle, and it is not solved.** Without an Apple Developer ID the
bundle is only ad-hoc signed; `spctl -a -t exec` rejects it, and macOS blocks the first
launch with a message that reads like malware being caught. For a program whose whole
argument is that it can be checked, being stopped by the operating system with "cannot
verify the developer" is close to the worst first impression available. Fixing it costs an
Apple Developer account at $99 a year, which is a decision, not a commit. The signing and
notarising steps are written and skipped when the secrets are absent, so they turn on the
moment the account exists — including `stapler staple`, since the ticket has to be in the
file for a machine that has been told to disconnect before running this.

`docs/Verifying_The_Download.md` says all of that to the customer, including the part that
does not flatter us: the file is not damaged, macOS says that about anything unsigned, and
the operating system is right that it cannot identify who published it. It also draws the
line around what the checks prove — the file matches the public source built in public —
and what nothing proves, which is that there is no malware in it. Offline running is
prevention, not evidence. The thing that actually protects the customer is moving the funds.

The Windows job's release step now creates the release only if it is absent and uploads with
`--clobber`. Two workflows and three jobs race for one tag; whichever arrives first should
win rather than the second one failing.

---

## 2026-08-22 — Paste was bound to Alt+V on Windows

**Changed:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`,
`.github/workflows/build-windows.yml`

The v0.1.7 Windows build failed its tests while macOS passed. The logs need authentication
to read, so this is what could be found by looking at the code for things that differ by
platform — and one of them is a real bug rather than a test problem.

Tk maps the `Command` modifier to `Mod1`, which is Cmd on macOS and **Alt** everywhere else.
Binding `<Command-v>` unconditionally put paste on Alt+V on Windows, beside a Ctrl+V that Tk
already handles, and took Alt+V from whatever else wanted it. Bound on macOS only now, which
is where it was needed: Tk's own Text bindings already cover Ctrl+V.

The clipboard test is the likely cause of the failure itself. It asserted that clearing
leaves the clipboard empty, which is true here and not guaranteed on a CI image where
something else may own it — the button already reports that case rather than hiding it, so
the test now accepts either answer and checks the right message for each.

The Windows test step runs verbose now. Not being able to read a failing build's log without
credentials made this guesswork; the next one will at least name the test in the summary.

---

## 2026-08-22 — A way to say thanks, kept away from the moment that matters

**Changed:** `recovery_gui.py`, `README.md`

The success screen is the wrong place for a QR code, and it is worth being precise about
why. That screen has just told someone to send everything they own to a new address, and to
check that address on their hardware wallet's screen before they do. A scannable "send here"
code beside those instructions is the exact shape of the attack that warning exists for, and
a mis-scan there is irreversible. It is also, in the moment someone is most grateful and
least critical, a program that has just seen their seed phrase asking them for money.

So: no QR in the program, text only, behind a button that has to be pressed, at the bottom
of everything else, after the steps that get the funds to safety. The diagnostic page has
the QR instead — there is no seed phrase on that page and nothing about it is urgent.

The same address is in this README so it can be compared against something outside the
program, which is the only real answer to "is this address really theirs".

**Upstream's donation addresses are untouched.** Rewriting them under text asking people to
thank the original authors would be taking money meant for someone else -- not a licensing
question. What the GPL does require is all still here: the licence, the fork notice, the
change log, the per-file notices, and the licence shipped inside the build.

The address was checked before being written into anything: 42 characters, decodes as
witness version 0 with a 20-byte program, and rejects a single-character change. The QR is
generated at build time as inline SVG and its rects were rebuilt back into a matrix and
compared with the encoder's own — so what is drawn is what was encoded. Nobody has scanned
it with a phone yet, which is the one check this machine cannot do.

---

## 2026-08-22 — Four letters per word, a window that scrolls, and icons with no box

**Changed:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`

All from using the built program rather than reading it.

**Pasting still did not work**, menu or no menu. Listing Tk's own class bindings showed why:
`Text` binds `<Control-v>` and the virtual `<<Paste>>`, and on macOS nothing raises that
virtual event from Command-v. A menu accelerator is a label, not a binding. `<Command-v>`
is bound explicitly now, along with a right-click menu on `<Button-3>`, `<Button-2>` and
`<Control-Button-1>`, since which of those is "right-click" depends on the platform.

**Four letters finish a word.** BIP39 chooses its wordlist so the first four letters
identify one — checked against the list rather than taken on trust: 2048 words, 2048
distinct four-letter prefixes, and 103 words shorter than four letters which are already
whole. Typing `aban` and pressing space gives `abandon`; `ac` and `wor` are left alone
because several words start with them. Unlike the substitution this fixes, it happens in
front of the person, on the key they were pressing anyway, and the checksum is rechecked
immediately.

**The last screen was cut off** — it carries the passphrase, five steps, and the run log,
and a fixed window simply lost the bottom of it with no sign there was more. The content
scrolls now, and the scrollbar appears only when a screen does not fit. The first attempt
at the wheel asked whether the scrollbar was on screen, which is packed and unpacked as
screens change: scrolling worked only with the pointer over the bar. It asks the viewport
whether it can move instead.

**The icons sat on a visible square in dark mode.** A `tk.Canvas` has to be painted some
colour and there is no colour that matches — on macOS the interior of a LabelFrame is not
the window background. They are drawn into a transparent `PhotoImage` now, so whatever the
theme puts behind them shows through without anyone having to know what colour it is. That
is the third approach: a Unicode glyph was an empty box on Windows, a canvas was a visible
box on macOS.

**A miss offers another seed phrase.** Someone with several can reach for the wrong one, and
"not found" looks identical either way. The resume point resets, since it counts candidates
rather than phrases and a finished run leaves it at the end.

---

## 2026-08-22 — Check the seed phrase before spending days on it, and paste it in the first place

**Changed:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`

Found by reading a real run's log, in a screenshot, where this line was sitting quietly
between two pieces of command-line advice:

    'reble' was in your guess, but it's not a valid seed word;
        trying 'rebel' instead.

btcrecover does not stop for a word it does not recognise. It substitutes the closest one
and says so — in a log box nobody opens. So a search can run for days against a seed phrase
its owner never typed, fail, and report nothing more useful than that the passphrase was not
found. 'reble' is one edit from 'rebel', and also from 'resemble' and 'relief'.

The phrase is now checked while it is being typed: every word against the BIP39 list, the
word count against the five lengths that exist, and then the **checksum**, which is the part
worth having — a valid phrase carries a few bits derived from the rest of it, so one wrong or
swapped word almost always fails it. A phrase that fails is refused rather than asked about;
it cannot be the phrase that made this wallet, so searching it burns days to reach the one
answer known in advance.

And when it is right the screen says so — `12단어 · 모두 BIP39 단어 · 체크섬 정상`. Someone
typing twenty-four words they wrote down years ago has no way to know they got them in, and
that line costs nothing to show.

**Pasting did not work at all.** Tk on macOS delivers Command-key shortcuts through the menu
bar, and this program had no menu, so Cmd+V did nothing in every field — including the one
where a seed phrase goes. Twenty-four words typed by hand is twenty-four chances to get one
wrong. There is an Edit menu now, and the word count follows a paste, which it did not: the
counter hung off KeyRelease and a paste produces no key event, so twelve words would sit in
the field under a label reading "0 단어".

**A button to empty the clipboard.** A seed phrase pasted in from a password manager or a
note is still sitting there afterwards, where the next program to ask can read it. The
button clears it and then checks whether it is actually empty before saying so — another
program can take the clipboard straight back, and a button that reports success when it
failed is worse than no button, because someone would stop worrying about it. Verified
against `pbpaste`: the system pasteboard really is emptied. What it cannot reach is written
next to it rather than left to be assumed — clipboard managers keep their own history, and
macOS may already have handed the text to another Apple device.

**Also:** the log drops advice nobody in a window can take (`--skip-pre-start`,
`--mnemonic-length`, `--no-dupchecks`, the internal wallet class name) and keeps the two
lines that matter — which crypto backend was chosen, and whether a word was substituted.
`방송` became `거래를 네트워크에 올리는` throughout: it is the right term and the wrong word,
since in Korean it means television first. Screens are repainted after being rebuilt, because
Tk 9 on macOS could leave the window showing nothing until a click. And the progress screen
leads with the percentage at 34pt with elapsed, remaining and rate beside it, while the
success screen opens with a green tick, "찾았습니다", and how long it took.

---

## 2026-08-22 — Ask about the network instead of locking the button, and make the window readable

**Changed:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`

The seed screen refused to start while a network route existed, and offered a checkbox
saying the reading was a false positive from a virtual adapter. That was wrong for the
common case it did not consider: someone trying the program out, who has no seed to protect
and no reason to unplug their machine. The only way past was to claim something untrue.

It asks now, at the moment it means something. The button always works; pressing it with a
live network opens one dialog that says what the risk is and defaults to cancel, so a stray
Return cannot start a search on a connected machine. The earlier screen still shows the
warning, and now adds that trying it out this way is fine.

Two of the three old tests were asserting the button was disabled, so they were rewritten
rather than repaired. A third problem surfaced immediately: every test that calls
`start_search()` now met a modal dialog and sat waiting for a human. The suite took 164
seconds instead of four before anyone noticed what it was doing. The fixture forces the
route check off.

**And the window was hard to read.** Every colour in it was a light-theme hex — `#555`,
`#666` — written when the only machine it had run on drew light windows. ttk follows the
system, so on a Mac in dark mode the window went dark and the text did not: grey on
near-black. Nothing failed and nothing warned; it was simply hard to read, which for a
program a nervous person is trying to follow is its own kind of failure. The palette is now
read from what the theme is actually drawing, and body text went from 11pt to 12pt.

---

## 2026-08-22 — A slot for what nobody remembers, and one search across several machines

**Changed:** `btcrecover/passphrase_grammar.py`, `btcrecover/embed.py`, `recovery_gui.py`,
`docs/Passphrase_Grammar.md`, tests

Both came from reading a reference token generator that had been left in the repository to
be reviewed — a CLI tool for btcrecover's `--tokenlist`, built around exhaustive patterns
like `%1,4ia` and around splitting the output so Linux does not kill it. Most of it does not
apply: the token-file OR-syntax traps are about a format this does not produce, `--dsw` is
already passed, and its advice to use an address with transaction history is wrong here,
since `--addrs` derives and compares rather than looking anything up on a chain. Two things
did.

**A `charset` slot.** Every other slot asks what a value might have been. This one is for
the run of characters where the honest answer is "no idea", and it enumerates an alphabet
instead. `{"type": "charset", "sets": ["lower", "upper"], "length": [1, 4]}` is 7,454,980
candidates — the same figure that reference quotes for `%1,4ia`, which is a useful check on
both. Shortest first, then base-N over the alphabet, one priority tier per length.

Its job is as much to show that a search is hopeless as to run one. Lower plus upper plus
digits at 1–6 is 57,731,386,986, which nobody should start; someone who could not express
the question at all left with the same uncertainty they arrived with.

**`"search": {"part": 3, "of": 7}`.** The reference splits files to avoid running out of
memory. That is not a problem here — `--skip` is O(1) and the count is exact — but splitting
is worth having for a different reason: a three-week search becomes three days on seven
machines, and a customer who would have given up on a laptop has an answer.

The parts tile the whole exactly, with the last taking the remainder rather than a rounded
chunk. Rounding down and multiplying leaves a tail nobody searched, and the run that skipped
the answer reports "not found" and looks exactly like a search that genuinely came up empty.
It is `part` and `of` rather than two indexes because 3 and 7 are numbers a person can retype
and 41,690,847 is not.

Found while writing it: `int(search.get("part") or 1)` turns a hand-typed `"part": 0` into
part 1 and searches the wrong stretch in silence — the exact failure the feature exists to
avoid. Refused now.

The recovery window says which part it is running, before the search and again if it finds
nothing. "Not found" after a seventh of the work reads as "it is not in this range", which
is the wrong conclusion and the one that makes someone stop.

**Also noticed while cross-checking:** the page's estimate and the program's count differ by
the number of Unicode normalization forms — `grammar.count()` never included them, because
the program tries each candidate's forms inside the search rather than as separate
candidates. Both numbers are right and they measure different things, but shown side by side
without that said, a customer comparing them concludes one is wrong. The window now says
"(정규화 형태별로 최대 2번씩)" next to the count.

---

## 2026-08-22 — Move the diagnostic page out of this repository

**Changed:** removed `webapp/` and `btcrecover/test/test_webapp_model.py`;
`.github/workflows/build-*.yml`, `docs/Passphrase_Grammar.md`, `.gitignore`

The page is the paid service; this fork is the tool it drives. The tool is GPL and public
because it must be. The page now lives in its own private repository, and deployment stops
being coupled to pushing the program.

It is worth being plain that this hides nothing about the page. It is entirely client-side,
so every visitor downloads its complete source — that is not a leak, it is how it works, and
it is what lets a customer confirm nothing is sent anywhere. What the split buys is that the
service's own work is not filed inside the GPL fork.

The cross-checks move with it rather than dying. They are the reason that test exists: the
page's address rules against `btcrseed`'s own classifier, its cost model against measurements
of this program, its post-recovery advice against `recovery_gui`'s. They now find this
checkout beside theirs, or at `BTCRECOVER_PATH`, and skip loudly when it is absent instead of
passing quietly.

While doing this, three things surfaced that a careless `git add -A` had swept into the
previous commit without anyone looking: `webapp/index.html` deleted (it was missing from the
working tree), and `webapp/.DS_Store` and a 57 KB `token_gen.html` added. The first is
restored, the second is now ignored, and the third was a reference file that had no business
being in a deploy directory.

Also corrected: an earlier report that the removed `webapp/아카이브.zip` was still being
served. It was not. That site answers **every** unknown path with 200 and the page itself, so
a status code alone says nothing — the response was HTML, not a zip.

---

## 2026-08-22 — Say what happens after recovery before anyone starts

**Changed:** `webapp/diagnostic.html`, `btcrecover/test/test_webapp_model.py`

The program explains how to move the funds on its success screen, which is the wrong time
to learn that a hardware wallet is needed — one ordered at that point arrives days later,
and if the seed did leak the risk runs for every one of them. The diagnostic page is read
before anyone buys anything, so it says it there too, in a modal beside the config
download: the moment someone decides to go ahead.

The steps are the ones the program gives — keep the recovery machine offline for good,
restore onto a hardware wallet, build the transaction in the phone app paired to it so the
signing happens on the device and the private key never reaches anything networked, one hop
straight to the final address, and check the receiving address on the device's own screen.
It adds the step the program cannot: order the hardware wallet now. And it ends where the
program's screen does not need to — reconnect the recovery computer only after the coins
have moved.

It also says plainly that running offline is prevention and not proof. Malware need not
send what it sees at the moment it sees it, and deleting the program does not delete what
the program wrote. Offline is worth doing; it is not evidence, and treating it as evidence
spends credibility that the published source and hash then have to earn back.

`AfterRecovery` in `test_webapp_model.py` checks the six load-bearing claims appear on both
surfaces, so the page and the program cannot drift into telling a customer different things.
Verified by deleting the address-check line from the page and the one-hop rule from the
program, and watching each fail on its own.

---

## 2026-08-22 — Shut the seed screen while the network is up, and say what to do after

**Changed:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`,
`docs/One_Binary_For_Everyone.md` (new), removed `webapp/아카이브.zip`

Offline running was being treated as an answer to "how do I know this has no malware". It
is not, and saying it is costs credibility that the parts which *are* verifiable then have
to pay for. Malware does not need to send a seed at the moment it sees it — it writes it
down and sends it when the machine reconnects, and deleting the program removes the
program, not what the program wrote. The connectivity check is also the suspected party's
own word for its own innocence.

So the claim is scaled back to what it is worth, and the program now does two things that
are worth something.

**The seed screen is shut while a network route exists.** The screen before it holds no
secret, so it still only warns; this one is where a secret is typed. It does not stop
malware — nothing here could — but it stops the honest failure of meaning to disconnect and
forgetting. An operating system reports a default route for VPN, virtual machine and
container adapters too, so an unbypassable check would lock out people who really are
offline: there is a deliberate override that says what it is. The warning is set larger
than body text and carries a drawn warning triangle rather than a Unicode glyph, which
renders as an empty box on a Windows without the right font.

**The success screen says what to do, not just that there is a risk.** Nobody can prove a
seed did not leak. What can be done is make a leak worthless, and that is an action the
customer takes in the next few minutes — on the last screen anyone reads.

The first version of these steps was wrong in a way worth writing down: it said to reconnect
this computer and then race. That is the one machine that should never go back online, and
it does not have to. Broadcasting needs a networked device, but the recovered seed can be
restored onto a hardware wallet, the transaction built in the phone app paired to it, and
the signing done inside the device — the private key never reaches anything networked, and
the recovery machine stays off the internet for good.

Two things were added on top of that. A single hop straight to the final address, because
passing through a phone wallet on the way costs a second fee and parks the coins under a key
held on a networked device. And, in its own line and its own weight, **verify the receiving
address on the hardware wallet's own screen**: the broadcasting device holds no key so it
has nothing to steal, but it can display one address and send to another, and that check is
the only defence and the step people skip.

For someone with no hardware wallet, waiting for delivery is not a neutral choice — if the
seed did leak, the race is already running. The screen says to move the coins somewhere they
control today, and move them again when the device arrives.

`docs/One_Binary_For_Everyone.md` records why every customer gets the same executable
rather than one built with their address compiled in: the licence obliges us to hand over
the means to remove any such check, upstream btcrecover is free anyway so there is nothing
to guard, per-customer builds destroy the one property that makes a published hash mean
anything, and building in the open would publish a list of addresses whose owners are
locked out of them.

`webapp/아카이브.zip` was a stale copy of the site from an earlier manual upload, tracked
in the repository and therefore served from the deployed page. A second, older, downloadable
version of the very page whose integrity customers are asked to check is exactly the wrong
thing to leave lying about. Removed.

---

## 2026-08-22 — Let the address decide the derivation path, and name a multisig one

**Changed:** `webapp/diagnostic.html`, `btcrecover/test/test_webapp_model.py`

The page asked the customer to pick a derivation path from a dropdown. That is a question
the address already answers: an address starting with `1` can only have come from BIP44,
`3` from BIP49, `bc1q` from BIP84, `bc1p` from BIP86. The program knows this and skips
paths that do not match. Asking anyway invited a wrong answer that loses the recovery.

The path is now derived from the address and shown as a finding, not a choice. What the
address genuinely cannot say is left as controls: which **account** (0, or several) and
whether to include **change** addresses. A collapsed field still allows a path to be typed
outright, for wallets that never followed BIP44 at all.

**A multisig address is now recognised and refused up front.** This came from a question
about whether multisig addresses are longer. They are, in exactly one case: bech32 witness
v0 carries a 20-byte program for single-signature (`bc1q…`, 42 characters) and a 32-byte
one for P2WSH (62 characters), which is how native segwit multisig is held. Checked against
the program: `_classify_address_script_type` returns `None` for P2WSH, so no derivation path
is filtered and the search runs to the very end and finds nothing — no error, just a search
that never had a chance.

Worse, the rule written an hour earlier matched on the `bc1q` prefix alone and would have
told the customer their multisig address was BIP84. Confidently wrong is worse than silent.
The page now reads the length, says the address is multisig, explains that a passphrase
cannot reach it without the co-signers' public keys, and states plainly that proceeding
will not find anything. Taproot is also 62 characters, so the witness version is read first
and P2TR is not caught by this.

For a `3…` address there is nothing to read: P2SH single-signature and P2SH multisig are
indistinguishable from outside. The page says so rather than implying it checked.

`PathDerivation` in `test_webapp_model.py` runs the page's rules and the program's
classifier over the same addresses and fails if they disagree — with P2WSH as the one place
the page must know more. Verified by reverting the length check and watching it go red.

---

## 2026-08-22 — Ask before measuring anyone's computer

**Changed:** `webapp/diagnostic.html`, `btcrecover/test/test_webapp_model.py`

The benchmark ran by itself when the page loaded. Technically that was fine — it reads no
CPU model, keeps nothing, and sends nothing — but starting to time a stranger's processor
the moment they arrive looks exactly like fingerprinting, and the customer has no way to
tell the difference from the outside. It now waits to be asked.

Until the button is pressed the estimate is computed from the reference machine and the
page says so. Pressing it measures; nothing is stored, so a reload returns to the
unmeasured state.

"무엇을 어떻게 재나요?" opens a modal that answers the suspicion directly rather than
asking to be trusted: what is computed (PBKDF2-HMAC-SHA512, 2048 rounds, on invented
strings — nothing the visitor typed), what cannot be read (CPU model, installed software,
history — the browser does not expose them), that `navigator.hardwareConcurrency` is the
single fact read and is shown in an editable field, that `connect-src 'none'` makes the
no-network claim something the browser enforces, and the actual source of the measuring
loop with the reason it takes a quantile rather than a mean.

`Consent` in `test_webapp_model.py` fails if `runBenchmark()` is ever called from anywhere
but a click handler, or if any browser storage appears. Checked by adding an auto-call and
confirming the test goes red.

---

## 2026-08-22 — Estimate the time on the customer's own machine

**Changed:** `webapp/diagnostic.html`, `btcrecover/test/test_webapp_model.py` (new),
`.github/workflows/build-windows.yml`

The page told every visitor the same three times, computed from invented parallel
efficiencies (0.55 / 0.70 / 0.80 for a 4-, 8- and 16-core machine). Since that number is
what someone decides to pay on, it is now measured instead.

**The visitor's machine is measured, not asked about.** A browser cannot read a CPU model,
and it should not be able to. It can run the same arithmetic the recovery runs:
PBKDF2-HMAC-SHA512, 2048 rounds, through WebCrypto. On the reference machine that reads
2,500/s against Python's 2,414/s — close enough to use almost directly. Core count comes
from `navigator.hardwareConcurrency`, with a field to override it for someone who will run
the recovery on a different computer. No network request is involved; the measurement never
leaves the page.

**Two things had to be right or the measurement is worse than none.**

* Run at page load, the identical code returned **0.86/s** where it returns 2,414/s once the
  page is idle — the main thread was busy with the page's own startup and every call
  waited. An average carries that straight through, and a customer whose browser hiccuped
  would be quoted centuries. The rate now comes from the 20th percentile of individual call
  times: interference can only make a call slower, never faster than the hardware allows.
  The benchmark is also deferred to `requestIdleCallback`, and a result outside 20–200,000/s
  is refused rather than shown.
* The calibration constant has to be taken with the same statistic it corrects. By average
  the browser reads 2,193/s; by the quantile, 2,500/s. Using the first to calibrate the
  second inflated every estimate by 14%.

**The cost model itself was 37% optimistic.** Re-measured at one thread, 20,000 candidates
per point: 1 address 645.0µs, 5 addresses 817.7µs, 10 addresses 1038.1µs, 20 addresses
1432.9µs. That is a straight line — 603.5µs fixed plus 41.5µs per address, within 2%. The
old model used 1/2400 + 32µs per address and forgot the ~190µs of Python that handling one
candidate costs on top of PBKDF2.

**Derivation paths are not a multiplier.** Ten addresses over one path measured 1038.1µs and
over three paths 1045.1µs. btcrecover skips paths that do not match the supplied address
type and says so in its own log. The page was multiplying by the number of paths chosen, so
anyone who picked "자동 (BIP44 + BIP49 + BIP84)" was quoted three times the real search.
It now counts matching paths the same way the program does, and says on screen when paths
are being skipped.

**Parallel scaling is measured too**, at 150,000 candidates per point so pool startup is not
mistaken for poor scaling: 1 thread 995/s, 2 → 1,962, 4 → 3,528, 8 → 6,367, 10 → 7,433,
12 → 8,654, 14 → 9,771. Fourteen cores give 9.8x, not 14x. This is one machine's curve and
is labelled as such.

End to end on the reference machine the page now predicts 982/s against 995/s measured at one
thread, and 9,632/s against 9,771/s at fourteen — 1.3% and 1.4%. That is a fit, not a
prediction on an unseen machine; the honest claim is that the single-core speed is measured
on the visitor's machine and the rest is measured on one machine and stated as such. The
program itself needs none of this: it shows remaining time from the rate it is actually
achieving.

`test_webapp_model.py` reads the constants back out of the page and checks they still
reproduce the runs they came from. The old constants were wrong by 37% and nothing could
have noticed — the numbers lived in JavaScript where no test could reach them.

---

## 2026-08-22 — Stop starving the worker processes (4x)

**Changed:** `btcrecover/btcrpass.py`, `btcrecover/embed.py`, `btcrecover/test/test_embed.py`

Found while measuring throughput for a machine-specific time estimate, not from any failure:
the embedded search was running at a quarter of the speed it should. 111,110 candidates took
48.0 seconds where the same search from the command line took 19.4.

btcrpass hands passphrases to its worker processes in chunks sized to last about a hundredth
of a second, computed from `est_secs_per_password`. `embed` passed `--skip-pre-start`, so that
estimate was not measured but taken from the wallet's own declared rate — 262/s against a real
1,041/s, off by 4x, producing chunks of 3 passphrases. Fourteen workers then spent most of
their time waiting on the parent to hand them the next three.

Two things were wrong, and both were mine:

* `--skip-pre-start` is an option this fork added, to save startup time. Measured, the
  benchmark it skips takes **0.13 seconds**. It is no longer passed.
* A hundredth of a second per chunk is too small on a machine with many cores regardless of
  the estimate. Swept on 14 cores: chunk 3 → 2,083/s, 14 → 6,635/s, 64 → 9,370/s, and flat
  from there through 1,024. `btcrpass.chunk_seconds_hint` lets an embedding caller raise the
  target; `embed.CHUNK_SECONDS` sets it to 0.05, short enough that Stop still feels immediate
  since the abort is only noticed between chunks.

Together: **48.0 seconds → 12.1 seconds**. The effective core count is now 6.9 of 14, which
agrees with the 918% CPU seen from the command line — the two measurements that disagreed
before now do not.

The command-line default is unchanged: `chunk_seconds_hint` is None there, and
`--skip-pre-start` still exists for anyone who wants it.

`WorkerFeeding` in `test_embed.py` guards this. Nothing failed while it was broken and nothing
would have — a search four times too slow looks exactly like a search.

---

## 2026-08-22 — Write down why --no-dupchecks is the default

**Changed:** `docs/Passphrase_Grammar.md`

Both `--no-eta` and `--no-dupchecks` were already passed, but only the first had a reason
recorded. Measured the second rather than leaving it as habit.

With no typo options it changes nothing — the grammar produces no duplicates, so the same
20,002 candidates either way. With typos on, duplicate checking would cut the work by about
29%: 5,094,989 candidates against 7,138,666. What it costs is around a hundred bytes per
distinct candidate, and it grows with the search — 100 MB at 600,000 candidates, 580 MB at
five million, 2.1 GB at twenty million. A hundred million would need ten gigabytes.

So the searches where 29% is worth having are the ones where the memory is not there, and a
recovery that dies partway through is worse than one that takes a third longer. It stays off,
and the reasoning is now in the docs rather than in someone's head.

---

## 2026-08-22 — Count the pool without building it

**Changed:** `webapp/diagnostic.html`

Asked whether a search running into the hundreds of millions would bog the page down. It
does not: `count()` multiplies over blocks and never builds a candidate, so six billion
costs 0.1 ms and 8×10¹⁷ costs the same.

The instinct came from btcrecover, where it is true — it counts by generating, which took
0.9 s for 1,111,110 candidates and 59 s for the 29,130,011 that one typo option turns them
into. That is why `embed` passes `--no-eta`: the count is already known, and half an hour
spent deciding how long a billion-candidate search will take is half an hour not searching.
Confirmed that the counting pass never runs.

One part of the page did scale with content. The pool slot built every subset in order to
count them — sixteen words is 65,535 of them, 28 ms on every keystroke. It sums binomials
now and keeps two subsets for sampling characters: 0.8 ms.

---

## 2026-08-22 — Three more ways an ordinary person's memory differs from the wallet

**Changed:** `btcrecover/passphrase_grammar.py`, `btcrecover/embed.py`, `webapp/diagnostic.html`

**Stray whitespace.** A space at either end of a passphrase is invisible in a field that
shows dots, and easy to acquire — typed by accident, or taken along by a copy-paste. Tried
outermost, so every candidate is attempted untouched before any is attempted with a space
attached: four times the work at worst, and no delay to a passphrase that had none.

**Leetspeak** (`a` → `@`, `o` → `0`). btcrecover ships the map and this fork already bundled
it; it simply was not offered. Five variants of a nine-character passphrase, and — like case
and capslock — none at all for Hangul, so the page disables it there.

**A wrong character, or one too many** (`--typos-replace`, `--typos-insert`). Tried as
lowercase letters and digits: the full printable set is nearly three times the work, 838
variants against 316, for characters a slip of the finger rarely produces.

Two things worth recording. `--typos-map` takes a single file and keeps only the last given,
so asking for both a neighbouring key and leetspeak silently dropped one — they are merged
into one map now, which btcrecover's own parser handles correctly since it accumulates
replacements per character. And the page's cost model returned early when no mistyping was
selected, skipping the whitespace multiplier, so whitespace alone appeared free.

Not added, deliberately. An empty passphrase: if it were empty the mnemonic alone would have
opened the wallet and nobody would be looking. Full-width characters and Korean spacing: real
but rarer, and each would widen every search.

---

## 2026-08-22 — Measure the ordering before changing it

**Added:** `utilities/passphrase_rank_benchmark.py`
**Changed:** `btcrecover/passphrase_grammar.py`

The priority model was one rule and no way to tell whether a second one would help. The
benchmark reports where the true passphrase lands, ordering on and off, over a fixed set of
cases — so a change to the model is an experiment rather than an assertion.

The baseline it measured showed the model was *hurting* two of them: a four-digit date
(`0301`) landed 1.7x later than with no ordering at all, and `1234` 1.2x later. Digit runs
are now tried as a year, then a date (`MMDD`, or `YYMMDD` for six), then something chosen to
be memorable, then anything else. Both cases now come out ahead, and the median position over
19 cases went from 20.15% of the space to 1.25%, with 15 of them inside the first 10%.

It also caught the cost of that, which is the point of having it. The six-digit date tier was
justified by birthdays, and the benchmark had no birthday in it — so it showed only the
1.3x penalty to a six-digit run that is not a date. With the missing cases added, both sides
are visible: 27x and 15x sooner for the birthdays, 1.0-1.3x slower for the rest.

Three grammar tests had pinned the old two-tier model's arithmetic. They assert properties
now — that cost never decreases as the search proceeds, and that a deep skip returns rather
than walking — so the next model change does not require rewriting them.

Tiers are bisected rather than walked, since "every valid YYMMDD" is over a thousand ranges,
and the leftover tier is computed as the complement of the claimed ranges. Building it by
walking the space took the grammar test suite from 0.7 seconds to 30.

---

## 2026-08-22 — Some of these words, not all of them

**Changed:** `btcrecover/passphrase_grammar.py`, `webapp/diagnostic.html`

"It was two or three of these five, I forget which" could not be expressed. A `pool` slot
takes a set of words and a `choose` range, and hands back each subset as **separate parts**,
so separators go between them and reordering applies across them.

Measured against a wallet whose passphrase was `사랑2014`, with an owner who remembers four
words but not which two: eight candidates and not found when assuming all four were used,
twenty candidates and found when asking for two or three of them.

This simplified the engine rather than complicating it. A pool contributes a varying number
of parts, which broke the assumption that a block's part count is fixed — so each subset size
became its own tier, and every tier now declares what it contributes. That removed the
special case for optional slots entirely: `count()` is a multiplication over blocks instead of
an enumeration over subsets, and `--skip` is always a division, where before it walked
whenever a grammar had an optional slot and priority ordering was off.

Case variants and `keystrokes` do not apply inside a pool; the words go in as given.

---

## 2026-08-22 — Recover a passphrase typed with the IME switched off

**Added:** `btcrecover/hangul_keys.py`, `btcrecover/test/test_hangul_keys.py`
**Changed:** `btcrecover/passphrase_grammar.py`, `webapp/diagnostic.html`

Korean is typed by pressing Latin keys and letting the IME assemble syllables. With the IME
off, someone setting `비밀번호` stores `qlalfqjsgh`. The field shows dots, so nothing looks
wrong, and it keeps working — the same wrong keystrokes go in every time — until the owner
tries to enter the passphrase they believe they chose.

`"keystrokes": true` on a words slot adds that form. Measured against a wallet holding
`qlalfqjsgh2024`, with an owner who remembers `비밀번호2024`: 20,000 candidates exhausted
without it, found at candidate 324 with it.

**A Latin word costs nothing** — its IME-off form is itself, and duplicates are dropped — so
the option is free for anyone it does not apply to. The page only asks the question when the
words contain Hangul.

The JavaScript tables are generated from `hangul_keys.py` rather than transcribed, and both
are held to the same vectors. Two of those vectors were wrong when first written by hand
(`왜` and `의사`); the code was right both times, which is the argument for deriving one side
from the other.

Only Hangul-to-keystrokes is handled. The reverse needs the IME's own composition automaton,
and half of it would produce sequences no wallet ever stored.

---

## 2026-08-22 — Ask whether they typed it correctly

**Changed:** `btcrecover/embed.py`, `webapp/diagnostic.html`, `recovery_gui.spec`

btcrecover can search around a mistyping — a transposition, a missed character, a neighbouring
key — and none of that was reachable from the config. It is now, as a `typos` section that
embed translates into `--typos-*` flags. btcrecover does the work; this only asks the question.

The diagnostic page asks it in the words someone would use ("옆 글자와 순서를 바꿔 쳤을 수
있어요") rather than by flag name, and shows what each answer costs before it is chosen. The
cost model comes from running `btcrecover --listpass` over sample passphrases, not from a
formula, and is stated as an upper bound: 529 against a measured 486 at two typos.

Two things fell out of measuring rather than assuming:

* **`case` and `capslock` do nothing to Hangul.** No letter case exists there. The page
  disables both when the sample has no Latin letters, instead of selling a Korean customer an
  option that multiplies their search by one.
* **`us-map.txt` does nothing to a passphrase with a capital in it** — seven variants of
  `TREZOr` against thirty-four for the shifted map. A passphrase is rarely all lower case, so
  `us-with-shifts-map.txt` is the one used, resolved against the package so a frozen build
  finds it, and now bundled.

---

## 2026-08-22 — Let the browser enforce the diagnostic page's promise

**Added:** `webapp/_headers`, `webapp/README.md`

The page tells visitors it makes no network request. That was true, and it was still only a
promise from the people asking them to type fragments of a passphrase into it. `_headers`
ships a Content-Security-Policy with `connect-src 'none'`, so the browser refuses `fetch`,
`XMLHttpRequest` and `sendBeacon` on the page's behalf, and a visitor can read the policy out
of the response headers rather than taking anyone's word for it.

Verified with the policy applied rather than assumed: all three refused, network log empty,
console naming the directive that stopped each one — and `config.json` still downloads,
because a blob download is not a connection.

`webapp/README.md` records which Cloudflare features have to stay off. Web Analytics, Rocket
Loader, Auto Minify, Email obfuscation and Bot Fight Mode all work by injecting a script, and
any one of them would both break the promise and make the page trip its own policy in front of
the customer. None are on by default; all are one click away.

---

## 2026-08-20 — Close the LevelDB files a Metamask wallet opens

**Changed:** `btcrecover/btcrpass.py`, `btcrecover/test/test_passwords.py`

Found while working out why the Windows build job sat on the test suite for twenty-two
minutes: the log was thousands of lines of `ResourceWarning: unclosed file`, walking through
`.ldb`, `.log` and `MANIFEST` files inside the Metamask test wallets.

`WalletMetamask.load_from_filename` built a `ccl_leveldb.RawLevelDb` and never closed it,
although the class supports both `close()` and the context manager protocol. The files still
closed eventually, when a finalizer got to them -- which is why this never showed up on
Linux, where an open file can be deleted anyway. On Windows it cannot, so the temporary
directory the test wallets live in stays undeletable until the collector happens to run.

Measured over five loads: twenty warnings before, none after. The file descriptor count does
not change, because refcounting was collecting them regardless; what changes is that closing
is now deterministic.

This is upstream's code and upstream's bug, and worth offering back — it is the reason their
own CI says `os: [ubuntu-24.04] # Test Ubuntu Only`.

**Changed:** `webapp/diagnostic.html`

The diagnostic page asked people to add a "word slot" and tick "optional". That is the
vocabulary of the thing being built, not of the person who lost a passphrase. It now asks
six questions — were there words, do you remember their capitalisation, were there digits
and do you know them or just how many, any symbols, what sat between the pieces, do you
remember the order — and skips the ones earlier answers made irrelevant. A single piece is
never asked about separators or ordering.

The answers write the same slots and separators the manual editor edits, so the count, the
estimate and config.json come from one representation either way. The editor is still
there, folded away, for what the questions cannot express.

Checked end to end: answering as a customer would ("배우자 이름, 결혼한 해, 느낌표") produces a
grammar the Python expander agrees with to the candidate, and running that config against
the unnormalized test wallet recovers 비밀번호2024 at candidate 124 of 20,000 in 0.6 seconds.

Verified on `windows-latest`, from a commit, on a public runner: dependencies, the four
suites covering this fork, a PyInstaller build in 22 seconds, and the built program
recovering the published BIP39 test vector in 0.86 seconds on the coincurve backend.
19.7 MB packaged, three minutes end to end.

Five failures got there, and they are worth keeping in view because only the third was
a mistake in the program rather than in how it was being checked:

1. `coincurve.__version__`, which coincurve does not define — a check that could only fail.
2. Upstream's own test suites, on a platform upstream does not test. Still running after
   twenty-two minutes, leaking file handles that Windows will not let go of.
3. **A real bug.** A Windows console encodes as cp1252, where Hangul does not exist, so
   the program died printing its own first line. The same crash would have hit a recovered
   Korean seed phrase at the moment of success.
4. and 5. A shell does not wait for a GUI-subsystem executable. Both runs checked the exit
   code and the report before the program had produced either. Two guesses at the cause
   were wrong; making the step report what it saw found it on the first try.

The program had been working on Windows since (3) was fixed. The last two failures were
the harness misreading it.

**Changed:** `recovery_gui.py`, `.gitignore`
**Added:** `recovery_gui.spec`, `.github/workflows/build-windows.yml`

A PyInstaller folder build, and a Windows build job that tests what it ships.

`recovery_gui.py --self-test [--report FILE]` recovers a known passphrase and exits
non-zero if it cannot. A windowed Windows build has no stdout, so the exit code carries the
verdict and the report file carries the detail — which means CI can check the same binary it
publishes, not a console-mode stand-in. It is equally useful to whoever downloaded the
program and wants to watch it work before showing it a seed phrase.

Building locally first turned up two failures that would have shipped:

* `wallycore` reaches its native library through `importlib.import_module("_wallycore")`,
  invisible to static analysis. Without it the build still runs and still passes its
  self-test, on the pure-Python secp256k1 — about two orders of magnitude slower, announced
  only by a warning. The build job now fails if that warning appears.
* `bitcoinlib` reads `config/VERSION` and `data/` at import time and will not load without
  them.

The build is a folder rather than one file, and UPX is off. A one-file build unpacks to a
temporary directory at each launch, which is the shape antivirus heuristics like least and
the shape that hides what shipped; a folder can be read and diffed.

Verified on the frozen binary: workers peak at one parent plus fourteen, exactly the
expected count, so `prepare_frozen_start()` does hold.

---

## 2026-08-20 — The offline recovery window

**Changed:** `btcrecover/embed.py`
**Added:** `recovery_gui.py`, `btcrecover/test/test_recovery_gui.py`

A tkinter window with four screens: check, load the config, type the seed phrase, watch it
run. Chosen over a heavier toolkit because this is a program strangers are asked to trust —
a small bundle with few dependencies is a smaller surface to explain and to reproduce.

The seed phrase is typed in the window and held only in memory. The resume file records a
candidate count and a fingerprint of the config, so a saved position cannot be applied to a
different search, and holds nothing else. Tests assert that.

Before any of it, the first screen reports whether the machine still has a network route --
read from the local routing table with no packet sent -- and offers a self-test that
recovers a known passphrase from the published BIP39 test vector, so an owner can watch the
program work before trusting it with their own seed.

Two problems found while building it:

* Tkinter allows one `Tk()` per process; a second one segfaults on macOS instead of raising.
  btcrseed creates its own root when it needs to prompt, so `embed.run` now lends it the
  host's. A SearchPlan supplies everything btcrseed would ask for, so this should be
  unreachable -- but a segfault there would take a running recovery with it.
* The self-test called `after()` from its worker thread, which tkinter does not allow. It
  polls from the main thread now, as the search already did.

---

## 2026-08-20 — Running a search from inside an application

**Changed:** `btcrecover/btcrpass.py`
**Added:** `btcrecover/embed.py`, `btcrecover/test/test_embed.py`

`btcrpass.main()` assumes a terminal: it prints, and it reports bad input by calling
`sys.exit`. Two hooks make it embeddable without disturbing that — `progress_hook(tried,
total)` fires as the search advances and once more when it stops, and `abort_event` is
polled between chunks so a stop button leaves nothing half-checked. Both default to unset,
and the command line behaves exactly as before.

`btcrecover.embed` wraps them. It builds the argv from a config.json, hands the grammar to
btcrpass as its `base_iterator` so no candidate reaches a pipe or a file, and returns a
`SearchResult` rather than exiting. The mnemonic is a parameter and never comes from the
config.

`WalletBIP39.normalization_of()` re-derives which Unicode form matched. The worker process
that found the match printed the form to its own stdout, which an embedding host never
sees; asking again costs at most four PBKDF2 rounds.

Two hazards found while building this, both of which would have surfaced first as a broken
executable:

* A host whose module-level code is not behind `if __name__ == "__main__"` fills the machine
  with processes within seconds, because each spawned worker re-runs the program. This is
  reproducible in a plain script, not only in a frozen build.
* A windowed PyInstaller build leaves `sys.stdout` as `None`. BTCRecover prints from its
  workers at the moment a match is found, so success would be the one outcome that crashes.
  `embed.prepare_frozen_start()` handles both, and must be the first thing a frozen entry
  point does.

---

## 2026-08-20 — Priority ordering for grammar candidates

**Changed:** `btcrecover/passphrase_grammar.py`, `webapp/diagnostic.html`

Candidates are now emitted in likelihood order rather than odometer order. Each slot splits
its values into tiers, a candidate's cost is the sum of its slots' tier numbers, and blocks
are emitted cheapest first. The model itself is currently a single rule — a four-digit run
is tried as a year (1900–2099) before anything else — kept small and contiguous so it can be
replaced by real case statistics without changing the machinery.

Measured rank of the correct passphrase in a 20,000-candidate grammar: 2,025 → 125 for
`비밀번호2024`, and 11,999 → 299 when the answer used the second of two words. A four-digit
run that is *not* a year loses about 200 places, which is the bounded cost of the same
choice.

Ordering changes only the order: the candidate set, and so `count()` and the quoted ETA, are
identical either way, and the tests assert it. `"priority": false` restores the raw product
order.

This also made resumption strictly better. A tier fixes whether each slot is empty, so every
candidate in a block costs the same to count past, and `--skip` is a division even when the
grammar has optional slots — where it previously had to walk. Skipping 200 million candidates
into a 222-million-candidate space is now immediate.

---

## 2026-08-20 — Passphrase grammars, and normalization on the passphrase-search path

**Changed:** `btcrecover/btcrpass.py`
**Added:** `btcrecover/passphrase_grammar.py`, `btcrecover/test/test_passphrase_grammar.py`,
`docs/Passphrase_Grammar.md`, `webapp/diagnostic.html`

`btcrpass.WalletBIP39` searches the passphrase itself with the mnemonic held fixed, which
is the path that matters when the mnemonic is already known. It normalized every candidate
to NFKD, so it had the same blind spot as the seed-search path fixed above, and the fix had
to be made twice. Both the CPU and OpenCL paths now try each requested form, and
`--passphrase-normalizations` is available on `btcrecover.py` as well as `seedrecover.py`.

`btcrecover.passphrase_grammar` expands a small JSON description of a passphrase -- some
remembered words, a digit range, an optional symbol -- into candidates on demand. Slots are
indexed rather than materialized, so a slot covering every digit string up to eight
characters is 111,111,110 candidates that cost nothing to construct, and the output is a
stream that pipes into `--passwordlist -`. The order is fixed and `--skip` resumes into it,
by division rather than by walking where no slot is optional.

`webapp/diagnostic.html` is a self-contained page that builds such a grammar from what a
user remembers and reports how large the search is, how long it would take, and which
remembered detail would shrink it most. It makes no network request; the grammar is
assembled in the browser and downloaded from a Blob.

Both implementations count candidates with the same formula, and the tests pin them to each
other. An optional slot that goes empty drops the separator that would have followed it, so
the count is not the plain product of the slot sizes.

Worth knowing when choosing a path: with one known mnemonic, `seedrecover.py
--passphrase-list` has a single unit of work and so uses one core no matter how many
workers it reports, and holds every passphrase in memory. Measured over 20,000 candidates,
`btcrecover.py --wallet-type bip39 --passwordlist -` finished the same search in 2.3s at
918% CPU against 17.2s at 100%.

---

## 2026-08-20 — Unicode normalization for non-ASCII BIP39 passphrases

**Changed:** `btcrecover/btcrseed.py`
**Added:** `btcrecover/test/test_cjk_passphrase.py`, `docs/CJK_Passphrase_Normalization.md`

BIP39 specifies that the passphrase is NFKD-normalized before it is used as the PBKDF2 salt, and
upstream implements exactly that. Some wallets never normalized what the user typed, however, and
hashed it as-is. For an ASCII passphrase this is indistinguishable; for Hangul, Kana, and other
scripts with composed and decomposed representations it is a different byte string, and therefore a
different seed and a different wallet. Such a wallet could not be recovered by upstream even when
both the mnemonic and the passphrase were exactly correct.

* New `--passphrase-normalizations` option, taking a comma-separated list of forms
  (`NFKD`, `NFC`, `NFD`, `NFKC`) or `all`. The default remains `NFKD`, so existing behaviour and the
  BIP39 spec are preserved unless the option is given.
* `WalletBIP39.config_mnemonic()` now derives one salt per *distinct* normalization form. Duplicates
  are dropped, so an ASCII passphrase still produces exactly one salt regardless of the forms
  requested, and Hangul produces two rather than four.
* Matches report which form they came from (`… Passphrase: 비밀번호2024 [NFC]`). NFC and NFD are
  indistinguishable on screen, and the recovered passphrase must be re-entered in the same form for
  the destination wallet to derive the same seed.
* `WalletAezeed` clears the form labels it inherits from `WalletBIP39.config_mnemonic()`, since it
  salts the passphrase verbatim and would otherwise misreport which normalization matched.

Electrum 2.x is unaffected: it defines and consistently applies its own normalization.

### Verification

`btcrecover/test/test_cjk_passphrase.py` contains a ground-truth generator that rebuilds the expected
addresses from the BIP39 and BIP32 specifications without importing btcrecover, anchored against the
published BIP39 test vector — so a bug in the normalization under test cannot mask itself.

```bash
python -m unittest btcrecover.test.test_cjk_passphrase
python -m unittest btcrecover.test.test_seeds
python -m unittest btcrecover.test.test_passwords
```

Note that `test_seeds` and `test_passwords` share global state and must be run in separate processes,
as `run-all-tests.py` does; this is pre-existing upstream behaviour.
