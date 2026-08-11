# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import unittest

from gsecrets.provider.oneplus_pcsc import PcscOtpError, PcscOtpTransport


class FakeReader:
    def __init__(self, name: str = "OnePlus 6 NFC 00 00") -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class FakeConnection:
    def __init__(self, responses=None, transmit_error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.transmit_error = transmit_error
        self.connected = False
        self.commands: list[bytes] = []

    def connect(self) -> None:
        self.connected = True

    def transmit(self, command: list[int]):
        self.commands.append(bytes(command))
        if self.transmit_error is not None:
            raise self.transmit_error
        return self.responses.pop(0)


class FakeCardService:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        self.exited = True
        return False


class FakeCardRequest:
    def __init__(self, service=None, wait_error: Exception | None = None) -> None:
        self.service = service
        self.wait_error = wait_error
        self.entered = False
        self.exited = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> bool:
        self.exited = True
        return False

    def waitforcard(self):
        if self.wait_error is not None:
            raise self.wait_error
        return self.service


class CardRequestTimeoutException(Exception):
    pass


class TransportHarness:
    def __init__(self, responses=None, transmit_error=None, wait_error=None) -> None:
        self.reader = FakeReader()
        self.connection = FakeConnection(responses, transmit_error)
        self.service = FakeCardService(self.connection)
        self.request = FakeCardRequest(self.service, wait_error)
        self.request_kwargs = None
        self.transport = PcscOtpTransport(
            readers_fn=lambda: [self.reader],
            card_request_factory=self._request_factory,
        )

    def _request_factory(self, **kwargs):
        self.request_kwargs = kwargs
        return self.request


class PcscOtpTransportTest(unittest.TestCase):
    SELECT_OTP = bytes.fromhex("00 A4 04 00 07 A0 00 00 05 27 20 01")
    RESPONSE = bytes(range(20))

    def successful_harness(self) -> TransportHarness:
        return TransportHarness(
            responses=[([], 0x90, 0x00), (list(self.RESPONSE), 0x90, 0x00)]
        )

    def test_reader_names_filters_oneplus_reader(self) -> None:
        transport = PcscOtpTransport(
            readers_fn=lambda: [
                FakeReader("Other Reader 00 00"),
                FakeReader("OnePlus 6 NFC 00 00"),
            ]
        )
        self.assertEqual(transport.reader_names(), ["OnePlus 6 NFC 00 00"])

    def test_reader_enumeration_error_returns_empty_discovery(self) -> None:
        def fail_readers():
            raise RuntimeError("reader manager unavailable")

        transport = PcscOtpTransport(readers_fn=fail_readers)
        self.assertEqual(transport.reader_names(), [])

    def test_slot_one_apdus_padding_response_and_cleanup(self) -> None:
        harness = self.successful_harness()
        challenge = bytes(range(32))

        response = harness.transport.challenge_response(
            str(harness.reader), 1, challenge, timeout=9
        )

        self.assertEqual(response, self.RESPONSE)
        self.assertEqual(harness.request_kwargs, {"timeout": 9, "readers": [harness.reader]})
        self.assertTrue(harness.connection.connected)
        self.assertEqual(harness.connection.commands[0], self.SELECT_OTP)
        self.assertEqual(
            harness.connection.commands[1],
            bytes((0x00, 0x01, 0x30, 0x00, 0x40))
            + challenge
            + bytes([0x20]) * 32,
        )
        self.assertTrue(harness.request.entered)
        self.assertTrue(harness.request.exited)
        self.assertTrue(harness.service.entered)
        self.assertTrue(harness.service.exited)

    def test_slot_two_apdu_keeps_full_length_challenge(self) -> None:
        harness = self.successful_harness()
        challenge = bytes(range(64))

        harness.transport.challenge_response(str(harness.reader), 2, challenge)

        self.assertEqual(
            harness.connection.commands[1],
            bytes((0x00, 0x01, 0x38, 0x00, 0x40)) + challenge,
        )

    def test_invalid_slot_is_rejected(self) -> None:
        transport = PcscOtpTransport(readers_fn=lambda: [])
        with self.assertRaisesRegex(PcscOtpError, "^YubiKey slot must be 1 or 2$"):
            transport.challenge_response("OnePlus 6 NFC 00 00", 3, b"x")

    def test_empty_and_oversize_challenges_are_rejected(self) -> None:
        transport = PcscOtpTransport(readers_fn=lambda: [])
        for challenge in (b"", bytes(65)):
            with self.subTest(length=len(challenge)):
                with self.assertRaisesRegex(
                    PcscOtpError,
                    "^YubiKey challenge must contain 1 to 64 bytes$",
                ):
                    transport.challenge_response("OnePlus 6 NFC 00 00", 1, challenge)

    def test_missing_selected_reader_is_rejected(self) -> None:
        transport = PcscOtpTransport(readers_fn=lambda: [FakeReader("Other Reader")])
        with self.assertRaisesRegex(
            PcscOtpError, "^OnePlus 6 NFC reader is unavailable$"
        ):
            transport.challenge_response("OnePlus 6 NFC 00 00", 1, b"x")

    def test_card_wait_timeout_releases_request(self) -> None:
        harness = TransportHarness(wait_error=CardRequestTimeoutException())
        with self.assertRaisesRegex(
            PcscOtpError, "^Timed out waiting for the NFC YubiKey$"
        ):
            harness.transport.challenge_response(str(harness.reader), 1, b"x")

        self.assertTrue(harness.request.entered)
        self.assertTrue(harness.request.exited)
        self.assertFalse(harness.service.entered)

    def test_transport_error_releases_request_and_service(self) -> None:
        harness = TransportHarness(transmit_error=RuntimeError("removed"))
        with self.assertRaisesRegex(
            PcscOtpError, "^NFC YubiKey communication failed$"
        ):
            harness.transport.challenge_response(str(harness.reader), 1, b"x")

        self.assertTrue(harness.request.exited)
        self.assertTrue(harness.service.exited)

    def test_non_success_status_is_rejected_and_resources_are_released(self) -> None:
        harness = TransportHarness(responses=[([], 0x6A, 0x82)])
        with self.assertRaisesRegex(
            PcscOtpError, "^YubiKey OTP applet returned 6A 82$"
        ):
            harness.transport.challenge_response(str(harness.reader), 1, b"x")

        self.assertTrue(harness.request.exited)
        self.assertTrue(harness.service.exited)

    def test_truncated_hmac_response_is_rejected(self) -> None:
        harness = TransportHarness(
            responses=[([], 0x90, 0x00), ([0] * 19, 0x90, 0x00)]
        )
        with self.assertRaisesRegex(
            PcscOtpError, "^YubiKey returned an invalid HMAC response$"
        ):
            harness.transport.challenge_response(str(harness.reader), 2, b"x")

        self.assertTrue(harness.request.exited)
        self.assertTrue(harness.service.exited)


if __name__ == "__main__":
    unittest.main()
