# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GLib, GObject

from gsecrets.provider.file_provider import FileProvider
from gsecrets.provider.yubikey_provider import YubiKeyProvider
from gsecrets.provider.secrets_composite import (
    encode_components,
    install_pykeepass_kdbx4_support,
    normalize_keyfile,
)

if TYPE_CHECKING:
    from gsecrets.utils import LazyValue

KEY_PROVIDERS = [FileProvider, YubiKeyProvider]

install_pykeepass_kdbx4_support()


class Providers(GObject.Object):
    def __init__(self, window: Adw.ApplicationWindow):
        super().__init__()

        self.providers = []
        self.salt: LazyValue[bytes] | None = None

        for key_provider in KEY_PROVIDERS:
            self.providers.append(key_provider(window))

    def get_key_providers(self) -> list:
        return self.providers

    def generate_composite_key_async(
        self,
        salt: LazyValue[bytes],
        callback: Gio.AsyncReadyCallback,
        cancellable: GLib.Cancellable = None,
    ) -> None:
        """Generate the in-memory composite key from selected providers."""
        self.salt = salt

        def generate_composite_key_task(task, self, _task_data, _cancellable):
            file_component = None
            yubikey_response = None

            for provider in self.providers:
                logging.debug("Generate key for %s", type(provider).__name__)
                try:
                    if not provider.generate_key(self.salt):
                        continue
                    logging.debug("Adding key from %s", type(provider).__name__)
                    if isinstance(provider, FileProvider):
                        file_component = normalize_keyfile(provider.key)
                    elif isinstance(provider, YubiKeyProvider):
                        yubikey_response = provider.key
                except ValueError as error:
                    task.return_error(GLib.Error(str(error)))
                    return

            if file_component is None and yubikey_response is None:
                logging.debug("No key providers in use, returning None")
                task.return_value(None)
                return

            try:
                composite_key = encode_components(file_component, yubikey_response)
            except ValueError as error:
                task.return_error(GLib.Error(str(error)))
                return
            task.return_value(composite_key)

        task = Gio.Task.new(self, cancellable, callback)
        task.run_in_thread(generate_composite_key_task)

    def generate_composite_key_finish(self, result):
        """Return the generated in-memory composite key."""
        _success, composite_key = result.propagate_value()
        return composite_key
