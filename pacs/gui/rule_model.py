# -*- coding: utf-8 -*-
"""规则表模型（QAbstractTableModel）。

为什么不用 QTableWidget：导入 ZeroOmega 后规则有 4000+ 条，QTableWidget 逐格建 item
会明显卡顿；用模型/视图只渲染可见行，几千行也流畅。
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_LABELS,
    PACS_ACTION_MIXED,
    PACS_MATCH_LABELS,
)
from pacs.pac.model import PacsDocument, PacsRule


class PacsRuleTableModel(QAbstractTableModel):
    HEADERS = ["启用", "#", "匹配类型", "内容", "动作", "代理地址", "备注"]
    COL_ENABLED = 0
    COL_INDEX = 1
    COL_MATCH = 2
    COL_CONTENT = 3
    COL_ACTION = 4
    COL_PROXY = 5
    COL_NOTE = 6

    def __init__(self, pms_document: Optional[PacsDocument] = None) -> None:
        super().__init__()
        self.pacs_document = pms_document or PacsDocument()

    # ------------------------------------------------------------------ 文档
    def pacs_set_document(self, pms_document: PacsDocument) -> None:
        self.beginResetModel()
        self.pacs_document = pms_document
        self.endResetModel()

    def pacs_rules(self) -> list[PacsRule]:
        return self.pacs_document.rules

    def pacs_rule_at(self, pms_row: int) -> Optional[PacsRule]:
        if 0 <= pms_row < len(self.pacs_document.rules):
            return self.pacs_document.rules[pms_row]
        return None

    # ------------------------------------------------------------------ 模型接口
    def rowCount(self, pms_parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if pms_parent.isValid() else len(self.pacs_document.rules)

    def columnCount(self, pms_parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if pms_parent.isValid() else len(self.HEADERS)

    def headerData(self, pms_section: int, pms_orientation: Qt.Orientation, pms_role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if pms_role != Qt.ItemDataRole.DisplayRole:
            return None
        if pms_orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[pms_section] if 0 <= pms_section < len(self.HEADERS) else None
        return str(pms_section + 1)

    def flags(self, pms_index: QModelIndex) -> Qt.ItemFlag:
        if not pms_index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if pms_index.column() == self.COL_ENABLED:
            return base | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        return base

    def data(self, pms_index: QModelIndex, pms_role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not pms_index.isValid():
            return None
        rule = self.pacs_rule_at(pms_index.row())
        if rule is None:
            return None
        column = pms_index.column()

        if pms_role == Qt.ItemDataRole.CheckStateRole and column == self.COL_ENABLED:
            return Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked
        if pms_role == Qt.ItemDataRole.DisplayRole:
            if column == self.COL_ENABLED:
                return ""
            if column == self.COL_INDEX:
                return str(pms_index.row() + 1)
            if column == self.COL_MATCH:
                return PACS_MATCH_LABELS.get(rule.match, rule.match)
            if column == self.COL_CONTENT:
                return rule.content
            if column == self.COL_ACTION:
                return PACS_ACTION_LABELS.get(rule.action, rule.action)
            if column == self.COL_PROXY:
                if rule.action == PACS_ACTION_DIRECT:
                    return ""
                return rule.proxy or "（默认）"
            if column == self.COL_NOTE:
                return rule.note
            return ""
        if pms_role == Qt.ItemDataRole.ToolTipRole:
            return rule.pacs_summary(self.pacs_document.default_proxy, self.pacs_document.default_scheme)
        if pms_role == Qt.ItemDataRole.TextAlignmentRole and column in (self.COL_ENABLED, self.COL_INDEX):
            return int(Qt.AlignmentFlag.AlignCenter)
        if pms_role == Qt.ItemDataRole.ForegroundRole and not rule.enabled:
            # 停用规则用系统「禁用文字」色，而不是写死的灰色（跟随系统主题）
            from PySide6.QtGui import QPalette
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if app is not None:
                return app.palette().color(
                    QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text
                )
            return None
        return None

    def setData(self, pms_index: QModelIndex, pms_value: Any, pms_role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not pms_index.isValid():
            return False
        rule = self.pacs_rule_at(pms_index.row())
        if rule is None:
            return False
        if pms_role == Qt.ItemDataRole.CheckStateRole and pms_index.column() == self.COL_ENABLED:
            rule.enabled = Qt.CheckState(pms_value) == Qt.CheckState.Checked
            self.dataChanged.emit(pms_index, pms_index, [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.ForegroundRole])
            return True
        return False

    # ------------------------------------------------------------------ 增删改
    def pacs_add_rule(self, pms_rule: PacsRule, pms_row: Optional[int] = None) -> int:
        if pms_row is None or pms_row < 0 or pms_row >= len(self.pacs_document.rules):
            pms_row = len(self.pacs_document.rules)
        self.beginInsertRows(QModelIndex(), pms_row, pms_row)
        self.pacs_document.rules.insert(pms_row, pms_rule)
        self.endInsertRows()
        return pms_row

    def pacs_update_rule(self, pms_row: int, pms_rule: PacsRule) -> bool:
        if not 0 <= pms_row < len(self.pacs_document.rules):
            return False
        self.pacs_document.rules[pms_row] = pms_rule
        self.pacs_refresh_row(pms_row)
        return True

    def pacs_remove_rows(self, pms_rows: list[int]) -> int:
        rows = sorted({row for row in pms_rows if 0 <= row < len(self.pacs_document.rules)}, reverse=True)
        for row in rows:
            self.beginRemoveRows(QModelIndex(), row, row)
            self.pacs_document.rules.pop(row)
            self.endRemoveRows()
        return len(rows)

    def pacs_move_row(self, pms_row: int, pms_delta: int) -> int:
        total = len(self.pacs_document.rules)
        target = pms_row + pms_delta
        if not (0 <= pms_row < total) or not (0 <= target < total):
            return pms_row
        rules = self.pacs_document.rules
        rules[pms_row], rules[target] = rules[target], rules[pms_row]
        self.pacs_refresh_row(pms_row)
        self.pacs_refresh_row(target)
        return target

    def pacs_batch_set(self, pms_rows: list[int], pms_key: str, pms_value: Any) -> int:
        changed = 0
        for row in pms_rows:
            if not 0 <= row < len(self.pacs_document.rules):
                continue
            setattr(self.pacs_document.rules[row], pms_key, pms_value)
            self.pacs_refresh_row(row)
            changed += 1
        return changed

    def pacs_refresh_row(self, pms_row: int) -> None:
        if 0 <= pms_row < len(self.pacs_document.rules):
            left = self.index(pms_row, 0)
            right = self.index(pms_row, self.columnCount() - 1)
            self.dataChanged.emit(left, right)

    def pacs_refresh_all(self) -> None:
        self.beginResetModel()
        self.endResetModel()

    # ------------------------------------------------------------------ 统计
    def pacs_stats_text(self) -> str:
        stats = self.pacs_document.pacs_stats()
        return (
            f"共 {stats.get('total', 0)} 条（启用 {stats.get('enabled', 0)} / 停用 {stats.get('disabled', 0)}）"
            f" · 直连 {stats.get('direct_rules', 0)} · 走代理 {stats.get('proxy_rules', 0)}"
        )
