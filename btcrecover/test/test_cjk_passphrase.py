#!/usr/bin/env python
# -*- coding: utf-8 -*-

# test_cjk_passphrase.py -- unit tests for Unicode normalization of BIP39 passphrases
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

"""BIP39 says the passphrase is NFKD-normalized before it becomes the PBKDF2 salt.
Some wallets never normalized what the user typed and hashed it as-is, which for
Hangul (and Kana, and anything else with composed/decomposed forms) is a different
byte string, and therefore a completely different wallet.

These tests pin down that gap: with the spec-mandated NFKD alone, a correct mnemonic
and a correct passphrase still fail to find such a wallet.
"""

import os, sys, unicodedata, unittest

if __name__ == '__main__':
    sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from btcrecover import btcrseed, embed


def setUpModule():
    """Run these under the same stdout the shipped program runs under.

    On a match btcrseed prints the recovered passphrase, and on Windows a bare
    interpreter encodes stdout as cp1252, in which Hangul has no representation --
    so the print raises UnicodeEncodeError at the exact moment of success. The
    program never meets that: embed._ensure_streams() runs before anything else,
    in every worker process too.

    These tests drive btcrseed directly, underneath that entry point, so they have
    to stand it up themselves. Calling the real function rather than repeating what
    it does means removing the protection from the product turns these red.
    """
    embed._ensure_streams()


# A standard BIP39 test mnemonic, so the only variable under test is the passphrase.
MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"

# Hangul: NFC composes each syllable into one code point, NFD/NFKD decomposes it into
# conjoining jamo. 16 bytes vs 34 bytes of UTF-8 for the same thing on screen.
PASSPHRASE_KO = "비밀번호" + "2024"   # 비밀번호2024

# m/44'/0'/0'/0/0 for MNEMONIC + PASSPHRASE_KO, one address per normalization form.
# Generated independently of btcrecover; test_ground_truth_is_independently_reproducible
# below regenerates and re-checks them whenever wallycore is available.
ADDR_NFKD = "152GYYPiXoJLbZqzDVvHYGfBHxbraQBrmj"  # a spec-compliant wallet
ADDR_NFC  = "12inFmZTGQ3YS2LRTHytWcSwRv3jH9yNLu"  # a wallet that skipped normalization
TEST_PATH = ["m/44'/0'/0'/0"]

try:
    import wallycore
    can_generate_ground_truth = True
except ImportError:
    can_generate_ground_truth = False


class NormalizationFormParsing(unittest.TestCase):

    def test_default_is_the_bip39_form(self):
        self.assertEqual(btcrseed.parse_passphrase_normalizations(None), ("NFKD",))
        self.assertEqual(btcrseed.parse_passphrase_normalizations(""), ("NFKD",))

    def test_all_expands_to_every_form(self):
        self.assertEqual(btcrseed.parse_passphrase_normalizations("all"),
                         btcrseed.PASSPHRASE_NORMALIZATION_FORMS)
        self.assertEqual(btcrseed.parse_passphrase_normalizations(" ALL "),
                         btcrseed.PASSPHRASE_NORMALIZATION_FORMS)

    def test_explicit_list_is_deduplicated_and_nfkd_leads(self):
        # NFKD is what the spec says, so it is always tried first when requested
        self.assertEqual(btcrseed.parse_passphrase_normalizations("nfc,nfkd,nfc"), ("NFKD", "NFC"))
        self.assertEqual(btcrseed.parse_passphrase_normalizations("NFC"), ("NFC",))

    def test_unknown_form_is_rejected(self):
        with self.assertRaises(ValueError):
            btcrseed.parse_passphrase_normalizations("NFKD,NFZ")
        with self.assertRaises(ValueError):
            btcrseed.parse_passphrase_normalizations(",")


class NormalizationChangesTheSeed(unittest.TestCase):
    """The premise, using nothing but the standard library."""

    def test_hangul_composes_and_decomposes_to_different_bytes(self):
        nfc  = unicodedata.normalize("NFC",  PASSPHRASE_KO).encode()
        nfkd = unicodedata.normalize("NFKD", PASSPHRASE_KO).encode()
        self.assertEqual(len(nfc), 16)
        self.assertEqual(len(nfkd), 34)
        self.assertNotEqual(nfc, nfkd)

    def test_ascii_is_identical_under_every_form(self):
        # so enabling every form costs an ASCII-passphrase search exactly nothing
        variants = {unicodedata.normalize(f, "btcr-test-password")
                    for f in btcrseed.PASSPHRASE_NORMALIZATION_FORMS}
        self.assertEqual(len(variants), 1)


class SaltExpansion(unittest.TestCase):
    """config_mnemonic() should turn one passphrase into one salt per *distinct* form."""

    def setUp(self):
        self.saved_forms = btcrseed.passphrase_normalizations

    def tearDown(self):
        btcrseed.passphrase_normalizations = self.saved_forms

    def _salts_for(self, passphrase, forms):
        btcrseed.passphrase_normalizations = forms
        wallet = btcrseed.WalletBIP39.create_from_params(addresses=[ADDR_NFKD], address_limit=2, path=TEST_PATH)
        wallet.config_mnemonic(MNEMONIC, lang="en", passphrases=[passphrase])
        return wallet

    def test_default_produces_exactly_one_salt(self):
        wallet = self._salts_for(PASSPHRASE_KO, ("NFKD",))
        self.assertEqual(len(wallet._derivation_salts), 1)
        self.assertEqual(wallet._derivation_salts[0],
                         unicodedata.normalize("NFKD", PASSPHRASE_KO).encode())

    def test_hangul_yields_two_distinct_salts(self):
        # NFC == NFKC and NFD == NFKD for this string, so four forms collapse to two
        wallet = self._salts_for(PASSPHRASE_KO, btcrseed.PASSPHRASE_NORMALIZATION_FORMS)
        self.assertEqual(len(wallet._derivation_salts), 2)
        self.assertEqual(sorted(wallet._derivation_salt_forms.values()), ["NFC", "NFKD"])

    def test_ascii_yields_one_salt_even_with_every_form_enabled(self):
        wallet = self._salts_for("btcr-test-password", btcrseed.PASSPHRASE_NORMALIZATION_FORMS)
        self.assertEqual(len(wallet._derivation_salts), 1)


class RecoveryAcrossNormalizationForms(unittest.TestCase):

    def setUp(self):
        self.saved_forms = btcrseed.passphrase_normalizations

    def tearDown(self):
        btcrseed.passphrase_normalizations = self.saved_forms

    def _find(self, address, forms):
        """Returns True if the correct mnemonic verifies against `address`."""
        btcrseed.passphrase_normalizations = forms
        wallet = btcrseed.WalletBIP39.create_from_params(addresses=[address], address_limit=2, path=TEST_PATH)
        wallet.config_mnemonic(MNEMONIC, lang="en", passphrases=[PASSPHRASE_KO])
        correct_ids = btcrseed.mnemonic_ids_guess
        found, _ = wallet.return_verified_password_or_false((correct_ids,))
        return found is not False

    def test_spec_compliant_wallet_is_found_by_default(self):
        self.assertTrue(self._find(ADDR_NFKD, ("NFKD",)))

    def test_non_normalizing_wallet_is_missed_by_default(self):
        """The gap. Mnemonic and passphrase are both exactly right, and it still fails."""
        self.assertFalse(self._find(ADDR_NFC, ("NFKD",)))

    def test_non_normalizing_wallet_is_found_with_all_forms(self):
        self.assertTrue(self._find(ADDR_NFC, btcrseed.PASSPHRASE_NORMALIZATION_FORMS))

    def test_spec_compliant_wallet_still_found_with_all_forms(self):
        """Enabling the extra forms must not regress the ordinary case."""
        self.assertTrue(self._find(ADDR_NFKD, btcrseed.PASSPHRASE_NORMALIZATION_FORMS))

    def test_match_reports_which_form_hit(self):
        # NFC and NFD are indistinguishable on screen, so the label is the only way
        # for a user to reproduce the recovered passphrase in another wallet.
        btcrseed.passphrase_normalizations = btcrseed.PASSPHRASE_NORMALIZATION_FORMS
        wallet = btcrseed.WalletBIP39.create_from_params(addresses=[ADDR_NFC], address_limit=2, path=TEST_PATH)
        wallet.config_mnemonic(MNEMONIC, lang="en", passphrases=[PASSPHRASE_KO])
        nfc_salt = unicodedata.normalize("NFC", PASSPHRASE_KO).encode()
        self.assertEqual(wallet._describe_salt(nfc_salt), PASSPHRASE_KO + " [NFC]")
        # _verify_seed() is also called with the salt prefixed, as the OpenCL path does
        self.assertEqual(wallet._describe_salt(b"mnemonic" + nfc_salt), PASSPHRASE_KO + " [NFC]")


@unittest.skipUnless(can_generate_ground_truth, "requires wallycore")
class GroundTruth(unittest.TestCase):
    """Rebuilds the expected addresses from the BIP39/BIP32 specs directly.

    This deliberately imports nothing from btcrecover: if it did, a bug in the
    normalization under test would cancel itself out and the tests above would
    pass against wrong addresses.
    """

    @staticmethod
    def _address_for(passphrase_form):
        import hashlib, wallycore as w
        mnemonic  = unicodedata.normalize("NFKD", MNEMONIC).encode()
        passphrase = unicodedata.normalize(passphrase_form, PASSPHRASE_KO).encode()
        seed = hashlib.pbkdf2_hmac("sha512", mnemonic, b"mnemonic" + passphrase, 2048, 64)
        master = w.bip32_key_from_seed(seed, 0x0488ADE4, 0)  # BIP32 mainnet private
        child  = w.bip32_key_from_parent_path_str(master, "m/44h/0h/0h/0/0", 0, 0)
        return w.bip32_key_to_address(child, w.WALLY_ADDRESS_TYPE_P2PKH,
                                      w.WALLY_ADDRESS_VERSION_P2PKH_MAINNET)

    def test_bip39_reference_vector(self):
        """Anchors the seed derivation itself against the published BIP39 test vector."""
        import hashlib
        seed = hashlib.pbkdf2_hmac("sha512", MNEMONIC.encode(), b"mnemonic" + b"TREZOR", 2048, 64)
        self.assertEqual(seed.hex(),
                         "c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e5349553"
                         "1f09a6987599d18264c1e1c92f2cf141630c7a3c4ab7c81b2f001698e7463b04")

    def test_ground_truth_is_independently_reproducible(self):
        self.assertEqual(self._address_for("NFKD"), ADDR_NFKD)
        self.assertEqual(self._address_for("NFC"),  ADDR_NFC)
        self.assertNotEqual(ADDR_NFKD, ADDR_NFC)

    def test_compatibility_forms_agree_for_hangul(self):
        self.assertEqual(self._address_for("NFD"),  ADDR_NFKD)
        self.assertEqual(self._address_for("NFKC"), ADDR_NFC)


if __name__ == '__main__':
    unittest.main()
