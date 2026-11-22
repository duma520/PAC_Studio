# -*- coding: utf-8 -*-
"""ZeroOmega 导入结果对话框：先给报告，再让用户选落地方式。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from pacs.gui.widgets import pacs_make_hint_label
from pacs.pac.omega_import import PacsOmegaImportResult


class PacsOmegaImportDialog(QDialog):
    """展示导入报告，并返回 (落地方式, 新方案名)。"""

    MODE_REPLACE = "replace"
    MODE_APPEND = "append"
    MODE_NEW = "new"

    def __init__(
        self,
        pms_result: PacsOmegaImportResult,
        pms_source_name: str = "",
        pms_parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(pms_parent)
        self.setWindowTitle("ZeroOmega PAC 导入结果")
        self.setMinimumSize(680, 560)
        self.pacs_result = pms_result
        self.pacs_mode = self.MODE_NEW
        self.pacs_new_name = pms_result.document.name or "从 ZeroOmega 导入"
        self.pacs_build_ui(pms_source_name)

    def pacs_build_ui(self, pms_source_name: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)

        title = QLabel(f"<b>已解析：{pms_source_name or 'ZeroOmega PAC'}</b>")
        root.addWidget(title)
        root.addWidget(pacs_make_hint_label(
            "下面是转换统计。确认无误后选择怎么落地——<b>替换</b>会覆盖当前方案的全部规则，"
            "<b>追加</b>会拼到当前方案末尾，<b>新建方案</b>最安全（原有方案一点不动）。"
        ))

        summary = QPlainTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText("\n".join(self.pacs_result.pacs_summary_lines()))
        summary.setMaximumHeight(190)
        root.addWidget(summary)

        if self.pacs_result.unsupported:
            root.addWidget(QLabel(f"无法自动转换的语句（{len(self.pacs_result.unsupported)} 条，原脚本里保留说明）："))
            unsupported = QPlainTextEdit()
            unsupported.setReadOnly(True)
            unsupported.setPlainText("\n".join(self.pacs_result.unsupported[:300]))
            unsupported.setMaximumHeight(130)
            root.addWidget(unsupported)
            root.addWidget(pacs_make_hint_label(
                "这些语句通常是「多个条件用 && 组合」或依赖 scheme 变量，强行拆开会改变语义，"
                "所以只登记不转换。需要的话可在导出的 PAC 里手工补。"
            ))

        root.addWidget(QLabel("<b>怎么落地？</b>"))
        self.pacs_radio_new = QRadioButton("新建一个方案（推荐，原方案不受影响）")
        self.pacs_radio_replace = QRadioButton("替换当前方案的全部规则")
        self.pacs_radio_append = QRadioButton("追加到当前方案末尾")
        self.pacs_radio_new.setChecked(True)
        root.addWidget(self.pacs_radio_new)
        root.addWidget(self.pacs_radio_replace)
        root.addWidget(self.pacs_radio_append)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("新方案名："))
        self.pacs_name_edit = QLineEdit(self.pacs_new_name)
        name_row.addWidget(self.pacs_name_edit, 1)
        root.addLayout(name_row)

        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消导入")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定导入")
        ok.setObjectName("primaryButton")
        ok.clicked.connect(self.pacs_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

    def pacs_accept(self) -> None:
        if self.pacs_radio_new.isChecked():
            self.pacs_mode = self.MODE_NEW
            self.pacs_new_name = self.pacs_name_edit.text().strip() or "从 ZeroOmega 导入"
        elif self.pacs_radio_replace.isChecked():
            self.pacs_mode = self.MODE_REPLACE
        else:
            self.pacs_mode = self.MODE_APPEND
        self.accept()
