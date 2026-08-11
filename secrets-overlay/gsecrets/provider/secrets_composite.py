# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import base64
import hashlib
from xml.etree import ElementTree

_MAGIC = b"ONEPLUS-SECRETS-KDBX4\x00"
_FILE_COMPONENT = 0x01
_YUBIKEY_COMPONENT = 0x02


class CompositeCredentialError(ValueError):
    """An invalid in-memory Secrets composite credential."""


def normalize_keyfile(keyfile_bytes: bytes) -> bytes:
    """Return the 32-byte KeePass key-file contribution."""
    try:
        tree = ElementTree.fromstring(keyfile_bytes)
        version_element = tree.find("Meta/Version")
        data_element = tree.find("Key/Data")
        if version_element is None or data_element is None or data_element.text is None:
            raise AttributeError("invalid key-file XML")

        version = version_element.text
        if version.startswith("1.0"):
            component = base64.b64decode(data_element.text)
        elif version.startswith("2.0"):
            component = bytes.fromhex(data_element.text.strip())
            declared_hash = bytes.fromhex(data_element.attrib["Hash"])
            computed_hash = hashlib.sha256(component).digest()[:4]
            if declared_hash != computed_hash:
                raise CompositeCredentialError("Key file has an invalid hash")
        else:
            raise AttributeError("unsupported key-file XML version")
    except (ElementTree.ParseError, UnicodeDecodeError, AttributeError):
        try:
            is_hex = len(keyfile_bytes) == 64
            if is_hex:
                int(keyfile_bytes, 16)
        except ValueError:
            is_hex = False

        if len(keyfile_bytes) == 32:
            component = keyfile_bytes
        elif is_hex:
            component = bytes.fromhex(keyfile_bytes.decode("ascii"))
        else:
            component = hashlib.sha256(keyfile_bytes).digest()

    if len(component) != 32:
        raise CompositeCredentialError("Key file has an invalid key length")
    return component


def encode_components(
    file_component: bytes | None,
    yubikey_response: bytes | None,
) -> bytes:
    flags = 0
    payload = bytearray(_MAGIC)

    if file_component is not None:
        if len(file_component) != 32:
            raise CompositeCredentialError("Key file has an invalid key length")
        flags |= _FILE_COMPONENT
    if yubikey_response is not None:
        if len(yubikey_response) != 20:
            raise CompositeCredentialError("YubiKey returned an invalid HMAC response")
        flags |= _YUBIKEY_COMPONENT
    if flags == 0:
        raise CompositeCredentialError("No credential components were selected")

    payload.append(flags)
    if file_component is not None:
        payload.extend(file_component)
    if yubikey_response is not None:
        payload.extend(yubikey_response)
    return bytes(payload)


def compute_enveloped_composite(password: str | None, envelope: bytes) -> bytes:
    if not envelope.startswith(_MAGIC):
        raise CompositeCredentialError("Invalid in-memory composite credential")

    position = len(_MAGIC)
    if len(envelope) <= position:
        raise CompositeCredentialError("Invalid in-memory composite credential")
    flags = envelope[position]
    position += 1
    if flags == 0 or flags & ~(_FILE_COMPONENT | _YUBIKEY_COMPONENT):
        raise CompositeCredentialError("Invalid in-memory composite credential")

    components = bytearray()
    if password is not None:
        components.extend(hashlib.sha256(password.encode("utf-8")).digest())

    if flags & _FILE_COMPONENT:
        end = position + 32
        if end > len(envelope):
            raise CompositeCredentialError("Invalid in-memory composite credential")
        components.extend(envelope[position:end])
        position = end

    if flags & _YUBIKEY_COMPONENT:
        end = position + 20
        if end > len(envelope):
            raise CompositeCredentialError("Invalid in-memory composite credential")
        components.extend(hashlib.sha256(envelope[position:end]).digest())
        position = end

    if position != len(envelope):
        raise CompositeCredentialError("Invalid in-memory composite credential")
    return hashlib.sha256(components).digest()


def install_pykeepass_kdbx4_support() -> None:
    """Teach this Secrets process to consume the in-memory component envelope."""
    from pykeepass.kdbx_parsing import kdbx4

    if getattr(kdbx4, "_oneplus_secrets_composite_installed", False):
        return

    original_compute = kdbx4.compute_key_composite

    def compute_key_composite(password=None, keyfile=None):
        if keyfile is not None and hasattr(keyfile, "read"):
            position = keyfile.tell() if hasattr(keyfile, "tell") else None
            if hasattr(keyfile, "seekable") and keyfile.seekable():
                keyfile.seek(0)
            keyfile_bytes = keyfile.read()
            if position is not None:
                keyfile.seek(position)
            if keyfile_bytes.startswith(_MAGIC):
                return compute_enveloped_composite(password, keyfile_bytes)
        return original_compute(password=password, keyfile=keyfile)

    kdbx4.compute_key_composite = compute_key_composite
    kdbx4._oneplus_secrets_composite_installed = True
