# -*- coding: utf-8 -*-
"""通用小控件与提示封装。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QProgressBar,
    QWidget,
)


def pacs_make_hint_label(pms_text: str, pms_parent: Optional[QWidget] = None) -> QLabel:
    """提示小字（自动换行，长文案不会撑破布局）。

    颜色取**系统调色板**的 PlaceholderText，而不是自定义色值：既保留「提示比正文淡一层」的
    层次，又跟随系统主题（浅色/深色）。界面整体不再使用任何自定义样式表。
    """
    label = QLabel(pms_text, pms_parent)
    label.setObjectName("hintLabel")
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    palette = label.palette()
    palette.setColor(
        QPalette.ColorRole.WindowText, palette.color(QPalette.ColorRole.PlaceholderText)
    )
    label.setPalette(palette)
    return label


class PacsProgressBar(QProgressBar):
    """带文字的进度条；空闲时隐藏，避免占位跳动。

    高度不写死，交给系统主题决定（不同 Windows 版本 / DPI 的默认高度不一样）。
    """

    def __init__(self, pms_parent: Optional[QWidget] = None) -> None:
        super().__init__(pms_parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(True)
        self.setMinimumWidth(220)
        self.setMaximumWidth(360)
        self.setVisible(False)

    def pacs_start(self, pms_text: str = "处理中…") -> None:
        self.setValue(0)
        self.setFormat(pms_text + " %p%")
        self.setVisible(True)

    def pacs_update(self, pms_percent: int, pms_text: str = "") -> None:
        self.setValue(max(0, min(100, int(pms_percent))))
        if pms_text:
            self.setFormat(pms_text + " %p%")

    def pacs_finish(self, pms_text: str = "完成") -> None:
        self.setValue(100)
        self.setFormat(pms_text + " 100%")

    def pacs_hide_after(self, pms_delay_ms: int = 1500) -> None:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(pms_delay_ms, lambda: self.setVisible(False))


def pacs_info(pms_parent: Optional[QWidget], pms_title: str, pms_text: str) -> None:
    QMessageBox.information(pms_parent, pms_title, pms_text)


def pacs_warn(pms_parent: Optional[QWidget], pms_title: str, pms_text: str) -> None:
    QMessageBox.warning(pms_parent, pms_title, pms_text)


def pacs_error(pms_parent: Optional[QWidget], pms_title: str, pms_text: str) -> None:
    QMessageBox.critical(pms_parent, pms_title, pms_text)


def pacs_confirm(pms_parent: Optional[QWidget], pms_title: str, pms_text: str) -> bool:
    reply = QMessageBox.question(
        pms_parent,
        pms_title,
        pms_text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes
