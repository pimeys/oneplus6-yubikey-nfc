# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import base64
import hashlib
import unittest

from gsecrets.provider.secrets_composite import (
    CompositeCredentialError,
    compute_enveloped_composite,
    encode_components,
    normalize_keyfile,
)


class SecretsCompositeTest(unittest.TestCase):
    FILE_COMPONENT = bytes(range(32))
    YUBIKEY_RESPONSE = bytes(range(20))

    def test_normalizes_version_two_xml_keyfile(self) -> None:
        short_hash = hashlib.sha256(self.FILE_COMPONENT).digest()[:4].hex().upper()
        keyfile = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<KeyFile><Meta><Version>2.0</Version></Meta><Key><Data Hash=\""
            + short_hash
            + '\">'
            + self.FILE_COMPONENT.hex().upper()
            + "</Data></Key></KeyFile>"
        ).encode()
        self.assertEqual(normalize_keyfile(keyfile), self.FILE_COMPONENT)

    def test_normalizes_version_one_xml_keyfile(self) -> None:
        keyfile = (
            "<KeyFile><Meta><Version>1.0</Version></Meta><Key><Data>"
            + base64.b64encode(self.FILE_COMPONENT).decode()
            + "</Data></Key></KeyFile>"
        ).encode()
        self.assertEqual(normalize_keyfile(keyfile), self.FILE_COMPONENT)

    def test_normalizes_raw_and_hex_keyfiles(self) -> None:
        self.assertEqual(normalize_keyfile(self.FILE_COMPONENT), self.FILE_COMPONENT)
        self.assertEqual(
            normalize_keyfile(self.FILE_COMPONENT.hex().encode()),
            self.FILE_COMPONENT,
        )
        arbitrary = b"arbitrary key file contents"
        self.assertEqual(normalize_keyfile(arbitrary), hashlib.sha256(arbitrary).digest())

    def test_rejects_invalid_version_two_hash(self) -> None:
        keyfile = (
            "<KeyFile><Meta><Version>2.0</Version></Meta>"
            "<Key><Data Hash=\"00000000\">"
            + self.FILE_COMPONENT.hex()
            + "</Data></Key></KeyFile>"
        ).encode()
        with self.assertRaisesRegex(
            CompositeCredentialError, "^Key file has an invalid hash$"
        ):
            normalize_keyfile(keyfile)

    def test_password_file_and_yubikey_match_keepassxc_composition(self) -> None:
        password = "temporary test password"
        envelope = encode_components(self.FILE_COMPONENT, self.YUBIKEY_RESPONSE)
        expected = hashlib.sha256(
            hashlib.sha256(password.encode()).digest()
            + self.FILE_COMPONENT
            + hashlib.sha256(self.YUBIKEY_RESPONSE).digest()
        ).digest()
        self.assertEqual(compute_enveloped_composite(password, envelope), expected)

    def test_file_only_and_yubikey_only_compositions(self) -> None:
        password_hash = hashlib.sha256(b"password").digest()
        file_envelope = encode_components(self.FILE_COMPONENT, None)
        yubikey_envelope = encode_components(None, self.YUBIKEY_RESPONSE)
        self.assertEqual(
            compute_enveloped_composite("password", file_envelope),
            hashlib.sha256(password_hash + self.FILE_COMPONENT).digest(),
        )
        self.assertEqual(
            compute_enveloped_composite("password", yubikey_envelope),
            hashlib.sha256(
                password_hash + hashlib.sha256(self.YUBIKEY_RESPONSE).digest()
            ).digest(),
        )

    def test_rejects_invalid_component_lengths_and_envelopes(self) -> None:
        with self.assertRaisesRegex(
            CompositeCredentialError, "^Key file has an invalid key length$"
        ):
            encode_components(bytes(31), self.YUBIKEY_RESPONSE)
        with self.assertRaisesRegex(
            CompositeCredentialError,
            "^YubiKey returned an invalid HMAC response$",
        ):
            encode_components(self.FILE_COMPONENT, bytes(19))
        valid = encode_components(self.FILE_COMPONENT, self.YUBIKEY_RESPONSE)
        for invalid in (b"not an envelope", valid[:-1], valid + b"extra"):
            with self.subTest(length=len(invalid)):
                with self.assertRaisesRegex(
                    CompositeCredentialError,
                    "^Invalid in-memory composite credential$",
                ):
                    compute_enveloped_composite("password", invalid)


if __name__ == "__main__":
    unittest.main()
