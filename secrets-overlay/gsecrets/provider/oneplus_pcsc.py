# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class PcscOtpError(ValueError):
    """A safe, user-facing NFC YubiKey transport error."""


class PcscOtpTransport:
    """Send YubiKey OTP challenge-response APDUs through the phone PC/SC reader."""

    _READER_PREFIX = "OnePlus 6 NFC"
    _SELECT_OTP = bytes.fromhex("00 A4 04 00 07 A0 00 00 05 27 20 01")
    _TRANSIENT_CARD_HRESULTS = (0x8010000C, 0x80100069)
    _MAX_EXCHANGE_ATTEMPTS = 3

    def __init__(
        self,
        readers_fn: Callable[[], list[object]] | None = None,
        card_request_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._readers_fn = readers_fn
        self._card_request_factory = card_request_factory
        self._lock = threading.Lock()

    def _get_readers_fn(self) -> Callable[[], list[object]]:
        if self._readers_fn is None:
            from smartcard.System import readers

            self._readers_fn = readers
        return self._readers_fn

    def _get_card_request_factory(self) -> Callable[..., Any]:
        if self._card_request_factory is None:
            from smartcard.CardRequest import CardRequest

            self._card_request_factory = CardRequest
        return self._card_request_factory

    @staticmethod
    def _is_card_request_timeout(error: Exception) -> bool:
        try:
            from smartcard.Exceptions import CardRequestTimeoutException
        except ImportError:
            return type(error).__name__ == "CardRequestTimeoutException"
        return isinstance(error, CardRequestTimeoutException) or (
            type(error).__name__ == "CardRequestTimeoutException"
        )

    @classmethod
    def _is_transient_card_error(cls, error: Exception) -> bool:
        current: BaseException | None = error
        for _depth in range(8):
            if current is None:
                return False
            hresult = getattr(current, "hresult", None)
            if isinstance(hresult, int) and (
                hresult & 0xFFFFFFFF
            ) in cls._TRANSIENT_CARD_HRESULTS:
                return True
            current = current.__cause__ or current.__context__
        return False

    def _matching_readers(self) -> list[object]:
        try:
            return [
                reader
                for reader in self._get_readers_fn()()
                if str(reader).startswith(self._READER_PREFIX)
            ]
        except Exception:
            return []

    def reader_names(self) -> list[str]:
        return [str(reader) for reader in self._matching_readers()]

    def challenge_response(
        self,
        reader_name: str,
        slot: int,
        challenge: bytes,
        timeout: int = 15,
    ) -> bytes:
        if slot not in (1, 2):
            raise PcscOtpError("YubiKey slot must be 1 or 2")
        if not 1 <= len(challenge) <= 64:
            raise PcscOtpError("YubiKey challenge must contain 1 to 64 bytes")

        if len(challenge) < 64:
            pad_len = 64 - len(challenge)
            padded_challenge = challenge + bytes([pad_len]) * pad_len
        else:
            padded_challenge = challenge

        slot_command = 0x30 if slot == 1 else 0x38
        challenge_apdu = bytes((0x00, 0x01, slot_command, 0x00, 0x40)) + padded_challenge

        with self._lock:
            reader = next(
                (reader for reader in self._matching_readers() if str(reader) == reader_name),
                None,
            )
            if reader is None:
                raise PcscOtpError("OnePlus 6 NFC reader is unavailable")

            deadline = time.monotonic() + timeout
            for attempt in range(self._MAX_EXCHANGE_ATTEMPTS):
                request_timeout = (
                    timeout
                    if attempt == 0
                    else max(0.0, deadline - time.monotonic())
                )
                try:
                    request_context = self._get_card_request_factory()(
                        timeout=request_timeout,
                        readers=[reader],
                    )
                    with request_context as request:
                        try:
                            card_service_context = request.waitforcard()
                        except Exception as error:
                            if self._is_card_request_timeout(error):
                                raise PcscOtpError(
                                    "Timed out waiting for the NFC YubiKey"
                                ) from error
                            raise PcscOtpError(
                                "NFC YubiKey communication failed"
                            ) from error

                        with card_service_context as card_service:
                            connection = card_service.connection
                            connection.connect()
                            _select_data, sw1, sw2 = connection.transmit(
                                list(self._SELECT_OTP)
                            )
                            self._check_status(sw1, sw2)
                            response, sw1, sw2 = connection.transmit(
                                list(challenge_apdu)
                            )
                            self._check_status(sw1, sw2)
                    break
                except PcscOtpError:
                    raise
                except Exception as error:
                    can_retry = (
                        self._is_transient_card_error(error)
                        and attempt + 1 < self._MAX_EXCHANGE_ATTEMPTS
                        and time.monotonic() < deadline
                    )
                    if can_retry:
                        continue
                    raise PcscOtpError(
                        "NFC YubiKey communication failed"
                    ) from error

        try:
            response_bytes = bytes(response)
        except (TypeError, ValueError) as error:
            raise PcscOtpError("YubiKey returned an invalid HMAC response") from error
        if len(response_bytes) != 20:
            raise PcscOtpError("YubiKey returned an invalid HMAC response")
        return response_bytes

    @staticmethod
    def _check_status(sw1: int, sw2: int) -> None:
        if (sw1, sw2) != (0x90, 0x00):
            raise PcscOtpError(
                f"YubiKey OTP applet returned {sw1:02X} {sw2:02X}"
            )
