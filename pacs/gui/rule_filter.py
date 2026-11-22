# -*- coding: utf-8 -*-
"""规则表搜索过滤器（单独成文件，避免主窗口与 UI 模块循环导入）。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSortFilterProxyModel
from PySide6.QtWidgets import QWidget

from pacs.constants import PACS_ACTION_LABELS, PACS_MATCH_LABELS


class PacsRuleFilterProxy(QSortFilterProxyModel):
    """在「内容 / 备注 / 类型 / 动作 / 代理」里做子串匹配。"""

    def __init__(self, pms_parent: Optional[QWidget] = None) -> None:
        super().__init__(pms_parent)
        self.pacs_text = ""

    def pacs_set_text(self, pms_text: str) -> None:
        self.pacs_text = str(pms_text or "").strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, pms_row: int, pms_parent) -> bool:  # noqa: N802 Qt 命名
        if not self.pacs_text:
            return True
        model = self.sourceModel()
        if model is None or not hasattr(model, "pacs_rule_at"):
            return True
        rule = model.pacs_rule_at(pms_row)
        if rule is None:
            return False
        haystack = " ".join(
            [
                rule.content,
                rule.note,
                PACS_MATCH_LABELS.get(rule.match, ""),
                PACS_ACTION_LABELS.get(rule.action, ""),
                rule.proxy,
            ]
        ).lower()
        return self.pacs_text in haystack
