# -*- coding: utf-8 -*-
"""主窗口 · 多方案管理（mixin）。

包含：方案下拉刷新、切换、新建、改名、复制、删除，以及默认动作行回填。
"""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog

from pacs.constants import PACS_ACTION_SOCKS5
from pacs.gui.widgets import pacs_confirm, pacs_error
from pacs.pac.model import PacsDocument


class PacsProfilesMixin:
    """依赖宿主窗口提供的属性：pacs_store / pacs_document / pacs_model / pacs_*_combo。"""

    # ------------------------------------------------------------------ 刷新
    def pacs_reload_all(self) -> None:
        self.pacs_document = self.pacs_store.pacs_load()
        self.pacs_model.pacs_set_document(self.pacs_document)
        self.pacs_refresh_profile_combo()
        self.pacs_refresh_default_row()
        self.pacs_refresh_status()

    def pacs_refresh_profile_combo(self) -> None:
        self.pacs_profile_combo.blockSignals(True)
        try:
            self.pacs_profile_combo.clear()
            active = self.pacs_store.pacs_active_name()
            for entry in self.pacs_store.pacs_profiles():
                self.pacs_profile_combo.addItem(entry["name"], entry["name"])
            index = self.pacs_profile_combo.findData(active)
            self.pacs_profile_combo.setCurrentIndex(max(0, index))
        finally:
            self.pacs_profile_combo.blockSignals(False)

    def pacs_refresh_default_row(self) -> None:
        doc = self.pacs_document
        self.pacs_default_action_combo.blockSignals(True)
        self.pacs_scheme_combo.blockSignals(True)
        try:
            action_index = self.pacs_default_action_combo.findData(doc.default_action)
            self.pacs_default_action_combo.setCurrentIndex(max(0, action_index))
            scheme_index = self.pacs_scheme_combo.findData(doc.default_scheme)
            self.pacs_scheme_combo.setCurrentIndex(max(0, scheme_index))
            if not self.pacs_default_proxy_edit.hasFocus():
                self.pacs_default_proxy_edit.setText(doc.default_proxy)
        finally:
            self.pacs_default_action_combo.blockSignals(False)
            self.pacs_scheme_combo.blockSignals(False)

    # ------------------------------------------------------------------ 切换
    def pacs_on_profile_changed(self, pms_index: int) -> None:
        name = self.pacs_profile_combo.itemData(pms_index)
        if not name or name == self.pacs_document.name:
            return
        self.pacs_save_now("切换方案")
        self.pacs_store.pacs_set_active(str(name))
        self.pacs_reload_all()
        self.pacs_refresh_preview_async()

    # ------------------------------------------------------------------ 增删改
    def pacs_create_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "新建方案", "给新方案起个名字：", text="新方案")
        if not ok or not name.strip():
            return
        doc = PacsDocument(
            name=name.strip(),
            default_action="proxy",
            default_proxy=self.pacs_settings.pacs_get_str("proxy.default_address", ""),
            default_scheme=self.pacs_settings.pacs_get_str(
                "proxy.default_scheme", PACS_ACTION_SOCKS5
            ),
        )
        if self.pacs_store.pacs_create_profile(name.strip(), doc):
            self.pacs_reload_all()
            self.pacs_refresh_preview_async()
        else:
            pacs_error(self, "新建失败", "方案名可能重复或文件不可写。")

    def pacs_rename_profile(self) -> None:
        old = self.pacs_document.name
        name, ok = QInputDialog.getText(self, "方案改名", "新名字：", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        if not self.pacs_store.pacs_rename_profile(old, name.strip()):
            pacs_error(self, "改名失败", "名字可能重复，或方案文件不可写。")
            return
        self.pacs_reload_all()

    def pacs_duplicate_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "复制方案", "新方案名：", text=f"{self.pacs_document.name} 副本"
        )
        if not ok or not name.strip():
            return
        if not self.pacs_store.pacs_duplicate_profile(self.pacs_document.name, name.strip()):
            pacs_error(self, "复制失败", "名字可能重复，或方案文件不可写。")
            return
        self.pacs_reload_all()

    def pacs_delete_profile(self) -> None:
        name = self.pacs_document.name
        if not pacs_confirm(
            self, "删除方案", f"确定删除方案「{name}」？这个方案的全部规则都会被删掉。"
        ):
            return
        if not self.pacs_store.pacs_delete_profile(name):
            pacs_error(self, "删除失败", "至少需要保留一个方案。")
            return
        self.pacs_reload_all()
        self.pacs_refresh_preview_async()
