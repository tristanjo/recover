# Checking the program before you run it

You are being asked to type a seed phrase into a program. "Trust us" is not an answer, so
here is what can be checked without trusting anyone, and — just as importantly — what these
checks do *not* prove.

## Everyone gets the same file

There is one build per platform, identical for every customer. That is what makes the
published hash worth anything: ten people can compare their downloads with each other and
with the number in the release, and a difference would show. A build made specially for you
would have a hash with nothing to compare it against.

```bash
# macOS
shasum -a 256 passphrase-recovery-<version>-macos-<arch>.dmg
```

```powershell
# Windows
Get-FileHash passphrase-recovery-<version>-windows.zip -Algorithm SHA256
```

Compare against the release page, and against the build log of the run that produced it —
the run is public and the log cannot be edited afterwards.

## Where it came from

```bash
gh attestation verify <the file you downloaded> --repo <owner>/<repo>
```

This ties the file to a commit in this repository and to the workflow run that built it. The
source is here; the build is not done on anyone's laptop.

## That it works

Both builds self-test. The first screen recovers a known passphrase from the published BIP39
test vector — real PBKDF2, real key derivation, real worker processes, in the binary that
ships. From a terminal:

```bash
# macOS
./passphrase-recovery.app/Contents/MacOS/passphrase-recovery --self-test
```

```powershell
# Windows
.\passphrase-recovery\passphrase-recovery.exe --self-test --report self-test.txt
```

## macOS will refuse to open it, and why

Unless the release notes say the build is notarised, macOS blocks it on first launch with a
message about the developer not being verified — or, on recent versions, one saying the app
is damaged. **It is not damaged.** macOS says that about anything downloaded without an
Apple Developer signature, which costs $99 a year and which this build may not yet carry.

That is a bad position for a program that asks you to be suspicious of it, and it is
honestly reported here rather than dressed up: the operating system is telling you it cannot
identify who published this, and it is right.

To open it anyway, having checked the hash above:

1. Move the app to Applications.
2. Open System Settings → Privacy & Security, scroll to Security, and press **Open Anyway**
   next to the message about the app.

Or, in Terminal:

```bash
xattr -dr com.apple.quarantine /Applications/passphrase-recovery.app
```

Do this only for a file whose hash you have checked. The command removes the marker that
made macOS ask, and it will not ask again.

Windows shows a similar SmartScreen warning for the same reason.

## What none of this proves

That the program has no malware in it. Nothing can prove that — not this document, not the
hash, not running offline.

Offline running is worth doing, and it is not evidence. Malware does not have to send what
it sees at the moment it sees it: it can write it down and send it the next time the machine
is connected. Deleting the program afterwards deletes the program, not what the program
wrote. And the program's own "you are offline" check is the suspected party vouching for
itself.

What the hash and the source do prove is that the file you are running is the one built from
code anyone can read, in public, from a commit you can look at. That is a real thing and it
is the strongest claim available.

The thing that actually protects you is not proof at all: **move the funds as soon as the
passphrase is found.** The program's success screen gives the steps, and the diagnostic page
gives them before you start so there is time to get a hardware wallet. Once the coins are in
a wallet whose seed never touched a computer, whether the old seed leaked stops mattering.

---

# For the maintainer: turning on macOS signing

Six repository secrets switch the signing and notarising steps on. Until all six exist the
build still runs, still self-tests, and publishes a hash — it just warns, loudly, that it is
unsigned, and says so in the release notes as well.

## 1. Enrol

[developer.apple.com/programs](https://developer.apple.com/programs/) — $99 a year. An
individual enrolment is enough; a company enrolment needs a D-U-N-S number and takes longer.
Approval usually lands within a day or two.

## 2. Create the Developer ID certificate

In Xcode: Settings → Accounts → your Apple ID → Manage Certificates → **+** → *Developer ID
Application*. Then in Keychain Access, find it under **login → My Certificates**, right-click
→ Export, save as `.p12`, and set a password.

Turn it into a secret:

```bash
base64 -i DeveloperID.p12 | pbcopy
```

Find the identity string — the whole quoted name, including the team ID in brackets:

```bash
security find-identity -v -p codesigning
```

## 3. Create an App Store Connect API key for notarising

[appstoreconnect.apple.com](https://appstoreconnect.apple.com) → Users and Access → Integrations
→ App Store Connect API → **+**. Give it the *Developer* role. Download the `.p8` — **it can
only be downloaded once.** Note the Key ID and the Issuer ID shown on the same page.

```bash
base64 -i AuthKey_XXXXXXXXXX.p8 | pbcopy
```

## 4. Add the secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

| Secret | What goes in it |
|---|---|
| `MACOS_CERT_P12` | base64 of the `.p12` from step 2 |
| `MACOS_CERT_PASSWORD` | the password set when exporting it |
| `MACOS_SIGN_IDENTITY` | e.g. `Developer ID Application: Your Name (AB12CD34EF)` |
| `MACOS_NOTARY_KEY` | base64 of the `.p8` from step 3 |
| `MACOS_NOTARY_KEY_ID` | the Key ID |
| `MACOS_NOTARY_ISSUER` | the Issuer ID (a UUID) |

## 5. Check it took

Push a tag and read the build log. The signing step prints `Signed with a Developer ID.`
Notarisation ends with `spctl` accepting the disk image. If a certificate is configured but
the signature did not take, the build **fails** rather than publishing something that looks
signed from the outside — that case is worse than an unsigned build, because nobody would
think to warn the customer.

Then download the release asset on a Mac that has never seen this build and open it. It
should open with no warning at all. If it still asks, the notarisation ticket was not
stapled — `stapler staple` runs in the same step, and the log will say.

The certificate expires after five years; the API key does not expire but can be revoked.
