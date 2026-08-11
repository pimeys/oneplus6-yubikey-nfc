# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

from gettext import gettext as _
from typing import TYPE_CHECKING

from gi.repository import Adw, Gio, GObject, Gtk

import gsecrets.config_manager as config
from gsecrets.provider.base_provider import BaseProvider
from gsecrets.provider.oneplus_pcsc import PcscOtpError, PcscOtpTransport

if TYPE_CHECKING:
    from gsecrets.database_manager import DatabaseManager
    from gsecrets.utils import LazyValue


class YubiKeyInfo(GObject.Object):
    __gtype_name__ = "YubiKeyInfo"

    def __init__(self, reader_name: str = "", slot: int = 0) -> None:
        super().__init__()
        self._reader_name = reader_name
        self._slot = slot

    @GObject.Property(type=str)
    def reader_name(self) -> str:
        return self._reader_name

    @GObject.Property(type=int)
    def slot(self) -> int:
        return self._slot

    @GObject.Property(type=str)
    def label(self) -> str:
        if not self._reader_name:
            return _("No Key")
        return _("{reader_name} — Slot {slot}").format(
            reader_name=self._reader_name,
            slot=self._slot,
        )


class YubiKeyProvider(BaseProvider):
    def __init__(self, _window) -> None:
        super().__init__()
        self._transport = PcscOtpTransport()
        self.active_key: YubiKeyInfo | None = None
        self.unlock_row: Adw.ComboRow | None = None
        self.create_row: Adw.ComboRow | None = None

    @property
    def available(self) -> bool:
        return True

    def _create_model(self) -> Gio.ListStore:
        model = Gio.ListStore.new(YubiKeyInfo)
        model.append(YubiKeyInfo())
        for reader_name in self._transport.reader_names():
            model.append(YubiKeyInfo(reader_name, 1))
            model.append(YubiKeyInfo(reader_name, 2))
        return model

    @staticmethod
    def _selection(info: YubiKeyInfo | None) -> tuple[str, int]:
        if info is None:
            return "", 0
        return info.reader_name, info.slot

    @staticmethod
    def _find_selection(model: Gio.ListStore, selection: tuple[str, int]) -> int:
        for position, info in enumerate(model):
            if (info.reader_name, info.slot) == selection:
                return position
        return 0

    def _refresh_row(
        self,
        row: Adw.ComboRow,
        selection: tuple[str, int] | None = None,
    ) -> None:
        if selection is None:
            selection = self._selection(row.get_selected_item())
        model = self._create_model()
        row.set_model(model)
        row.set_selected(self._find_selection(model, selection))
        self.active_key = row.get_selected_item()

    def _create_factory(self) -> Gtk.SignalListItemFactory:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        return factory

    def create_unlock_widget(self, database_manager: DatabaseManager) -> Gtk.Widget:
        row = Adw.ComboRow()
        row.set_title(_("YubiKey"))
        row.set_use_subtitle(True)
        row.set_expression(Gtk.PropertyExpression.new(YubiKeyInfo, None, "label"))
        row.set_factory(self._create_factory())
        row.connect("notify::selected", self._on_row_selected)
        self.unlock_row = row

        refresh_button = Gtk.Button()
        refresh_button.set_valign(Gtk.Align.CENTER)
        refresh_button.add_css_class("flat")
        refresh_button.set_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text(_("Rescan NFC YubiKey slots"))
        refresh_button.connect("clicked", self._on_unlock_refresh_clicked)
        row.add_suffix(refresh_button)

        selection = ("", 0)
        provider_config = config.get_provider_config(
            database_manager.path,
            "YubiKeyProvider",
        )
        if provider_config:
            reader_name = provider_config.get("reader")
            slot = provider_config.get("slot")
            if isinstance(reader_name, str) and slot in (1, 2):
                selection = reader_name, slot
        self._refresh_row(row, selection)
        return row

    def create_database_row(self) -> Gtk.Widget:
        row = Adw.ComboRow()
        row.set_title(_("YubiKey"))
        row.set_use_subtitle(True)
        row.set_expression(Gtk.PropertyExpression.new(YubiKeyInfo, None, "label"))
        row.set_factory(self._create_factory())
        row.connect("notify::selected", self._on_row_selected)
        self.create_row = row

        refresh_button = Gtk.Button()
        refresh_button.set_valign(Gtk.Align.CENTER)
        refresh_button.add_css_class("flat")
        refresh_button.set_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text(_("Rescan NFC YubiKey slots"))
        refresh_button.connect("clicked", self._on_create_refresh_clicked)
        row.add_suffix(refresh_button)

        self._refresh_row(row, ("", 0))
        return row

    def _on_row_selected(
        self,
        row: Adw.ComboRow,
        _param: GObject.ParamSpec,
    ) -> None:
        self.active_key = row.get_selected_item()

    def _on_unlock_refresh_clicked(self, _button: Gtk.Button) -> None:
        if self.unlock_row is not None:
            self._refresh_row(self.unlock_row)

    def _on_create_refresh_clicked(self, _button: Gtk.Button) -> None:
        if self.create_row is not None:
            self._refresh_row(self.create_row)

    @staticmethod
    def _on_factory_setup(_factory, list_item) -> None:
        label = Gtk.Label()
        label.set_halign(Gtk.Align.START)
        list_item.set_child(label)

    @staticmethod
    def _on_factory_bind(_factory, list_item) -> None:
        label = list_item.get_child()
        info = list_item.get_item()
        info.bind_property(
            "label",
            label,
            "label",
            GObject.BindingFlags.SYNC_CREATE,
        )

    def generate_key(self, salt: LazyValue[bytes]) -> bool:
        self.raw_key = None
        if self.active_key is None or self.active_key.slot not in (1, 2):
            return False

        self.emit(
            self.show_message,
            _("Hold the YubiKey against the upper rear of the phone"),
        )
        try:
            response = self._transport.challenge_response(
                self.active_key.reader_name,
                self.active_key.slot,
                salt.value,
                15,
            )
        except PcscOtpError as error:
            raise ValueError(str(error)) from error
        finally:
            self.emit(self.hide_message)

        self.raw_key = response
        return True

    def config(self) -> dict:
        if self.active_key is None or self.active_key.slot not in (1, 2):
            return {}
        return {
            "reader": self.active_key.reader_name,
            "slot": self.active_key.slot,
        }

    def clear_input_fields(self) -> None:
        self.raw_key = None
