# -*- coding: utf-8 -*-
"""单条规则编辑对话框（全中文 + 实时大白话解释）。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
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
    PACS_ACTION_LABELS,
    PACS_ACTION_MIXED,
    PACS_ACTIONS,
    PACS_MATCH_LABEL_TO_VALUE,
    PACS_MATCH_LABELS,
    PACS_MATCH_TYPES,
)
from pacs.gui.widgets import pacs_make_hint_label
from pacs.pac.model import PacsRule

_PLACEHOLDERS = {
    "domain_suffix": "例如 baidu.com（自动包含 www.baidu.com 等所有子域）",
    "domain_wildcard": "例如 *.google.com 或 cdn*.example.com",
    "keyword": "例如 google（网址或域名里包含它就算命中）",
    "url_regex": "例如 ^https?://(www\\.)?example\\.com/",
    "host_regex": "例如 ^(?:.*\\.)?example\\.com$",
    "ip_cidr": "例如 ***已脱敏***-内网IP/16 或 ***已脱敏***-内网IP",
    "all": "「全部流量」不需要填内容",
}

_MATCH_HELP = {
    "domain_suffix": "按域名结尾判断，最常用。填 baidu.com 就能同时匹配 baidu.com 和 mail.baidu.com。",
    "domain_wildcard": "域名里允许通配。*.example.com 表示 example.com 及其所有子域；cdn*.x.com 表示 cdn 开头的子域。",
    "keyword": "网址或域名里出现这段文字就算命中，最省事但容易误伤。",
    "url_regex": "对完整网址做正则匹配，适合按路径精确控制，需要懂一点正则。",
    "host_regex": "对域名做正则匹配（ZeroOmega 导入时保留的原始规则就属于这种）。",
    "ip_cidr": "按目标 IP 段判断，例如 ***已脱敏***-内网IP/16 表示整个内网。",
    "all": "无视网站，直接给出结果。放在规则表靠前会让后面的规则全部失效。",
}


class PacsRuleDialog(QDialog):
    def __init__(
        self,
        pms_rule: Optional[PacsRule] = None,
        pms_default_proxy: str = "",
        pms_default_scheme: str = "SOCKS5",
        pms_parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(pms_parent)
        self.setWindowTitle("编辑一条分流规则" if pms_rule else "添加一条分流规则")
        self.setMinimumWidth(560)
        self.pacs_rule = (pms_rule.pacs_clone() if pms_rule else PacsRule())
        self.pacs_default_proxy = pms_default_proxy
        self.pacs_default_scheme = pms_default_scheme
        self.pacs_build_ui()
        self.pacs_load_rule()

    # ------------------------------------------------------------------ UI
    def pacs_build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.pacs_match_combo = QComboBox()
        for match in PACS_MATCH_TYPES:
            self.pacs_match_combo.addItem(PACS_MATCH_LABELS[match], match)
        self.pacs_match_combo.currentIndexChanged.connect(self.pacs_on_match_changed)
        form.addRow("① 怎么认网站", self.pacs_match_combo)

        self.pacs_content_edit = QLineEdit()
        form.addRow("② 匹配内容", self.pacs_content_edit)

        self.pacs_action_combo = QComboBox()
        for action in PACS_ACTIONS:
            self.pacs_action_combo.addItem(PACS_ACTION_LABELS[action], action)
        self.pacs_action_combo.currentIndexChanged.connect(self.pacs_refresh_explain)
        form.addRow("③ 命中后怎么走", self.pacs_action_combo)

        self.pacs_proxy_edit = QLineEdit()
        self.pacs_proxy_edit.setPlaceholderText(
            f"留空 = 用默认代理 {self.pacs_default_proxy or '（未设置）'}"
        )
        self.pacs_proxy_edit.textChanged.connect(self.pacs_refresh_explain)
        form.addRow("④ 单独指定代理地址", self.pacs_proxy_edit)

        self.pacs_fallback_check = QCheckBox("混合模式失败时再尝试直连（返回 …; DIRECT）")
        form.addRow("", self.pacs_fallback_check)

        self.pacs_note_edit = QLineEdit()
        self.pacs_note_edit.setPlaceholderText("给自己看的备注，随便写")
        form.addRow("⑤ 备注", self.pacs_note_edit)

        self.pacs_enabled_check = QCheckBox("启用这条规则")
        self.pacs_enabled_check.setChecked(True)
        form.addRow("", self.pacs_enabled_check)

        self.pacs_proxy_hint = pacs_make_hint_label(
            f"代理地址格式为 <b>IP:端口</b>，默认外部代理是 <b>{self.pacs_default_proxy or '（未设置）'}</b>。"
            "「直连」不需要填地址。"
        )
        form.addRow("", self.pacs_proxy_hint)
        root.addLayout(form)

        self.pacs_explain = QLabel("")
        self.pacs_explain.setWordWrap(True)
        self.pacs_explain.setObjectName("hintLabel")
        self.pacs_explain.setMinimumHeight(46)
        self.pacs_explain.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        root.addWidget(self.pacs_explain)
        root.addWidget(pacs_make_hint_label(
            "提示：规则从上往下判断，<b>先命中先生效</b>。同一件事别写两条；"
            "「全部流量」放在最后才安全。"
        ))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("确定")
        ok.setObjectName("primaryButton")
        ok.clicked.connect(self.pacs_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        root.addLayout(buttons)

    # ------------------------------------------------------------------ 数据
    def pacs_load_rule(self) -> None:
        rule = self.pacs_rule
        index = self.pacs_match_combo.findData(rule.match)
        self.pacs_match_combo.setCurrentIndex(max(0, index))
        self.pacs_content_edit.setText(rule.content)
        action_index = self.pacs_action_combo.findData(rule.action)
        self.pacs_action_combo.setCurrentIndex(max(0, action_index))
        self.pacs_proxy_edit.setText(rule.proxy)
        self.pacs_fallback_check.setChecked(bool(rule.fallback_direct))
        self.pacs_note_edit.setText(rule.note)
        self.pacs_enabled_check.setChecked(rule.enabled)
        self.pacs_on_match_changed()

    def pacs_on_match_changed(self) -> None:
        match = self.pacs_match_combo.currentData()
        self.pacs_content_edit.setPlaceholderText(_PLACEHOLDERS.get(match, ""))
        self.pacs_content_edit.setEnabled(match != "all")
        self.pacs_refresh_explain()

    def pacs_refresh_explain(self) -> None:
        match = self.pacs_match_combo.currentData()
        action = self.pacs_action_combo.currentData()
        self.pacs_fallback_check.setVisible(action == PACS_ACTION_MIXED)
        address = self.pacs_proxy_edit.text().strip() or self.pacs_default_proxy or "（未设置地址）"
        action_text = {
            "DIRECT": "直连（不经过代理）",
            "PROXY": f"走 HTTP 代理 {address}",
            "SOCKS5": f"走 SOCKS5 代理 {address}",
            "MIXED": f"先试 HTTP 代理再试 SOCKS5（{address}）",
        }.get(action, "按动作执行")
        self.pacs_explain.setText(
            f"<b>这条规则的意思是：</b>{_MATCH_HELP.get(match, '')}<br>"
            f"命中后：<b>{action_text}</b>。"
        )

    def pacs_accept(self) -> None:
        match = self.pacs_match_combo.currentData()
        action = self.pacs_action_combo.currentData()
        rule = PacsRule(
            match=match,
            content=self.pacs_content_edit.text().strip(),
            action=action,
            proxy=self.pacs_proxy_edit.text().strip(),
            fallback_direct=self.pacs_fallback_check.isChecked(),
            note=self.pacs_note_edit.text().strip(),
            enabled=self.pacs_enabled_check.isChecked(),
        )
        ok, reason = rule.pacs_validate(self.pacs_default_proxy)
        if not ok:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "这条规则还不能保存", reason)
            return
        self.pacs_rule = rule
        self.accept()
