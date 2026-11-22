# -*- coding: utf-8 -*-
"""设置对话框。

纪律：**改动即时保存**（勾选/输入立刻写盘），不设「保存」按钮；
唯一的「关闭」只负责退出对话框。这样用户不会因为忘了点保存而丢配置。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pacs.constants import (
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_COMPILE_MODE_LABELS,
    PACS_COMPILE_MODES,
    PACS_DEFAULT_PROXY_ADDRESS,
    PACS_DEFAULT_PROXY_SCHEME,
)
from pacs.gui.widgets import pacs_make_hint_label
from pacs.paths import PacsRuntimePaths
from pacs.settings import PacsSettingsManager
from pacs.utils import pacs_is_valid_proxy_address, pacs_open_in_explorer


class PacsSettingsDialog(QDialog):
    def __init__(
        self,
        pms_paths: PacsRuntimePaths,
        pms_settings: PacsSettingsManager,
        pms_autostart: Optional[object] = None,
        pms_parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(pms_parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(620)
        self.pacs_paths = pms_paths
        self.pacs_settings = pms_settings
        self.pacs_autostart = pms_autostart
        self.pacs_build_ui()

    # ------------------------------------------------------------------ UI
    def pacs_build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # ---- 默认外部代理 ----
        self.pacs_address_edit = QLineEdit(
            self.pacs_settings.pacs_get_str("proxy.default_address", PACS_DEFAULT_PROXY_ADDRESS)
        )
        self.pacs_address_edit.editingFinished.connect(self.pacs_save_address)
        form.addRow("默认外部代理地址", self.pacs_address_edit)
        form.addRow("", pacs_make_hint_label(
            f"新建方案时用它作为默认代理。出厂默认 <b>{PACS_DEFAULT_PROXY_ADDRESS}</b>，格式 IP:端口。"
        ))

        self.pacs_scheme_combo = QComboBox()
        for value, label in (
            (PACS_ACTION_PROXY, "HTTP 代理（PROXY）"),
            (PACS_ACTION_SOCKS5, "SOCKS5（与 ZeroOmega 一致）"),
            (PACS_ACTION_MIXED, "混合（先 PROXY 再 SOCKS5）"),
        ):
            self.pacs_scheme_combo.addItem(label, value)
        index = self.pacs_scheme_combo.findData(
            self.pacs_settings.pacs_get_str("proxy.default_scheme", PACS_DEFAULT_PROXY_SCHEME)
        )
        self.pacs_scheme_combo.setCurrentIndex(max(0, index))
        self.pacs_scheme_combo.currentIndexChanged.connect(self.pacs_save_scheme)
        form.addRow("默认代理协议", self.pacs_scheme_combo)
        form.addRow("", pacs_make_hint_label(
            "⚠ <b>Windows 自带的 IE/WinINET 对 SOCKS5 支持不完整</b>；Chrome / Edge / Firefox 自带 PAC 引擎"
            "可以正常按 SOCKS5 走。如果某个老程序不认，改成 HTTP 代理或用混合模式。"
        ))

        self.pacs_mixed_check = QCheckBox("混合模式下，两种代理都失败时再尝试直连（追加 ; DIRECT）")
        self.pacs_mixed_check.setChecked(
            self.pacs_settings.pacs_get_bool("proxy.mixed_add_direct_fallback", False)
        )
        self.pacs_mixed_check.stateChanged.connect(
            lambda: self.pacs_settings.psm_set(
                "proxy.mixed_add_direct_fallback", self.pacs_mixed_check.isChecked()
            )
        )
        form.addRow("", self.pacs_mixed_check)

        # ---- 编译 ----
        self.pacs_mode_combo = QComboBox()
        for value in PACS_COMPILE_MODES:
            self.pacs_mode_combo.addItem(PACS_COMPILE_MODE_LABELS[value], value)
        index = self.pacs_mode_combo.findData(
            self.pacs_settings.pacs_get_str("pac.compile_mode", "optimized")
        )
        self.pacs_mode_combo.setCurrentIndex(max(0, index))
        self.pacs_mode_combo.currentIndexChanged.connect(
            lambda: self.pacs_settings.psm_set("pac.compile_mode", self.pacs_mode_combo.currentData())
        )
        form.addRow("编译方式", self.pacs_mode_combo)
        form.addRow("", pacs_make_hint_label(
            "优化版把几千条域名合并成查表，判定快、体积小；可读版逐条 if，方便人看，但文件更大。"
        ))

        # ---- 系统代理 ----
        self.pacs_restore_check = QCheckBox("退出程序时，还原我原来的系统代理设置")
        self.pacs_restore_check.setChecked(
            self.pacs_settings.pacs_get_bool("system_proxy.restore_on_exit", True)
        )
        self.pacs_restore_check.stateChanged.connect(
            lambda: self.pacs_settings.psm_set(
                "system_proxy.restore_on_exit", self.pacs_restore_check.isChecked()
            )
        )
        form.addRow("", self.pacs_restore_check)

        # ---- 托盘 ----
        self.pacs_tray_check = QCheckBox("启用托盘图标")
        self.pacs_tray_check.setChecked(self.pacs_settings.pacs_get_bool("ui.tray_enabled", True))
        self.pacs_tray_check.stateChanged.connect(
            lambda: self.pacs_settings.psm_set("ui.tray_enabled", self.pacs_tray_check.isChecked())
        )
        form.addRow("", self.pacs_tray_check)

        self.pacs_close_tray_check = QCheckBox("关闭窗口时最小化到托盘（不退出程序）")
        self.pacs_close_tray_check.setChecked(
            self.pacs_settings.pacs_get_bool("ui.close_to_tray", True)
        )
        self.pacs_close_tray_check.stateChanged.connect(
            lambda: self.pacs_settings.psm_set(
                "ui.close_to_tray", self.pacs_close_tray_check.isChecked()
            )
        )
        form.addRow("", self.pacs_close_tray_check)

        # ---- 开机自启 ----
        self.pacs_autostart_check = QCheckBox("开机后自动应用当前方案的 PAC")
        self.pacs_autostart_check.stateChanged.connect(self.pacs_save_autostart)
        if self.pacs_autostart is not None and hasattr(self.pacs_autostart, "pacs_is_enabled"):
            try:
                self.pacs_autostart_check.blockSignals(True)
                self.pacs_autostart_check.setChecked(bool(self.pacs_autostart.pacs_is_enabled()))
            except Exception:  # noqa: BLE001
                self.pacs_autostart_check.setChecked(False)
            finally:
                self.pacs_autostart_check.blockSignals(False)
        form.addRow("", self.pacs_autostart_check)

        # ---- 数据目录 ----
        self.pacs_data_label = QLabel(str(self.pacs_paths.prt_data_dir))
        self.pacs_data_label.setWordWrap(True)
        form.addRow("数据目录", self.pacs_data_label)
        open_button = QPushButton("打开数据目录")
        open_button.clicked.connect(lambda: pacs_open_in_explorer(self.pacs_paths.prt_data_dir))
        form.addRow("", open_button)

        root.addLayout(form)
        root.addWidget(pacs_make_hint_label(
            "所有设置都是<b>改动即保存</b>，关掉对话框不会丢。"
            "<br>PAC 文件：<b>" + str(self.pacs_paths.prt_pac_file) + "</b>"
        ))

        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("关闭")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.accept)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    # ------------------------------------------------------------------ 保存
    def pacs_save_address(self, *pms_args) -> None:
        text = self.pacs_address_edit.text().strip()
        if text and not pacs_is_valid_proxy_address(text):
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "地址格式不对", "代理地址要写成 IP:端口，例如 ***已脱敏***-内网IP:20808")
            self.pacs_address_edit.setText(
                self.pacs_settings.pacs_get_str("proxy.default_address", PACS_DEFAULT_PROXY_ADDRESS)
            )
            return
        self.pacs_settings.psm_set("proxy.default_address", text or PACS_DEFAULT_PROXY_ADDRESS)

    def pacs_save_scheme(self, *pms_args) -> None:
        self.pacs_settings.psm_set("proxy.default_scheme", self.pacs_scheme_combo.currentData())

    def pacs_save_autostart(self, *pms_args) -> None:
        enabled = self.pacs_autostart_check.isChecked()
        self.pacs_settings.psm_set("autostart.enabled", enabled)
        if self.pacs_autostart is not None and hasattr(self.pacs_autostart, "pacs_set_enabled"):
            ok = bool(self.pacs_autostart.pacs_set_enabled(enabled))
            if not ok:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self,
                    "设置开机自启失败",
                    "写注册表失败。可能被安全软件拦截，或当前用户没有权限。",
                )
