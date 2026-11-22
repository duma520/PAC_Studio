# -*- coding: utf-8 -*-
"""主窗口 · 规则表操作（mixin）。

包含：选中行解析、增删改、上下移、批量改、右键菜单、默认项编辑、搜索。
"""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMenu

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_LABELS,
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
)
from pacs.gui.dialogs.rule_dialog import PacsRuleDialog
from pacs.gui.widgets import pacs_confirm, pacs_info, pacs_warn
from pacs.pac.model import PacsRule
from pacs.utils import pacs_split_proxy


class PacsRulesMixin:
    """依赖宿主窗口：pacs_model / pacs_table / pacs_filter / pacs_document 等。"""

    # ------------------------------------------------------------------ 选择
    def pacs_selected_rows(self) -> list[int]:
        """当前选中的规则行号（升序去重）。

        性能要求：规则表可能有 4000+ 条，用户一次全选就是 4000+ 行。
        **不能用 `selectedRows()`**：它会为每一行构造 QModelIndex 包装再逐个
        `mapToSource`，实测 4557 行要 3.7 秒，右键直接卡死。
        这里用 `selection()` 返回的连续区间：
            - 没有搜索过滤时，代理模型行号 == 源模型行号，直接展开区间；
            - 有过滤时才逐个转换（过滤后行数有限）。
        """
        selection = self.pacs_table.selectionModel()
        if selection is None:
            return []
        proxy = self.pacs_filter
        has_filter = bool(getattr(proxy, "pacs_text", ""))
        same_mapping = (not has_filter) and proxy.rowCount() == self.pacs_model.rowCount()
        rows: list[int] = []
        for rng in selection.selection():
            top, bottom = rng.top(), rng.bottom()
            if top < 0:
                continue
            if same_mapping:
                rows.extend(range(top, bottom + 1))
            else:
                for row in range(top, bottom + 1):
                    source = proxy.mapToSource(proxy.index(row, 0))
                    if source.isValid():
                        rows.append(source.row())
        if not rows:
            current = self.pacs_table.currentIndex()
            if current.isValid():
                rows.append(proxy.mapToSource(current).row())
        return sorted(set(rows))

    def pacs_selected_count(self) -> int:
        """选中条数（O(区间数)，全选 4000+ 行也是常数级）。菜单只用来分分支。"""
        selection = self.pacs_table.selectionModel()
        if selection is None:
            return 0
        total = 0
        for rng in selection.selection():
            if rng.top() >= 0:
                total += rng.bottom() - rng.top() + 1
        return total

    def pacs_is_proxy_row_selected(self, pms_proxy_row: int) -> bool:
        """某个「视图行号」是否已在选择内（同样避免构造大量 index）。"""
        selection = self.pacs_table.selectionModel()
        if selection is None:
            return False
        for rng in selection.selection():
            if rng.top() <= pms_proxy_row <= rng.bottom():
                return True
        return False

    def pacs_select_row(self, pms_row: int) -> None:
        source = self.pacs_model.index(pms_row, 0)
        proxy_index = self.pacs_filter.mapFromSource(source)
        if proxy_index.isValid():
            self.pacs_table.selectRow(proxy_index.row())
            self.pacs_table.scrollTo(proxy_index)

    # ------------------------------------------------------------------ 增删改
    def pacs_add_rule(self) -> None:
        dialog = PacsRuleDialog(
            None,
            self.pacs_document.default_proxy,
            self.pacs_document.default_scheme,
            self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        rows = self.pacs_selected_rows()
        insert_at = rows[-1] + 1 if rows else len(self.pacs_document.rules)
        self.pacs_model.pacs_add_rule(dialog.pacs_rule, insert_at)
        self.pacs_on_model_changed()
        self.pacs_refresh_preview_async()

    def pacs_edit_rule(self) -> None:
        rows = self.pacs_selected_rows()
        if not rows:
            pacs_info(self, "提示", "请先选中一条规则。")
            return
        row = rows[0]
        rule = self.pacs_model.pacs_rule_at(row)
        if rule is None:
            return
        dialog = PacsRuleDialog(
            rule, self.pacs_document.default_proxy, self.pacs_document.default_scheme, self
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self.pacs_model.pacs_update_rule(row, dialog.pacs_rule)
        self.pacs_on_model_changed()
        self.pacs_refresh_preview_async()

    def pacs_remove_rules(self) -> None:
        rows = self.pacs_selected_rows()
        if not rows:
            return
        if not pacs_confirm(self, "删除规则", f"确定删除选中的 {len(rows)} 条规则？"):
            return
        self.pacs_model.pacs_remove_rows(rows)
        self.pacs_on_model_changed()
        self.pacs_refresh_preview_async()

    def pacs_move_rule(self, pms_delta: int) -> None:
        rows = self.pacs_selected_rows()
        if len(rows) != 1:
            pacs_info(self, "提示", "上移 / 下移一次只能移动一条规则。")
            return
        new_row = self.pacs_model.pacs_move_row(rows[0], pms_delta)
        self.pacs_select_row(new_row)
        self.pacs_on_model_changed()

    # ------------------------------------------------------------------ 修改（单选 / 多选通用）
    def pacs_set_action(self, pms_rows: list[int], pms_action: str) -> int:
        """把指定行的动作直接改成 pms_action（1 条或多条都走这里）。返回改动条数。"""
        if not pms_rows:
            return 0
        changed = self.pacs_model.pacs_batch_set(pms_rows, "action", pms_action)
        self.pacs_on_model_changed()
        self.pacs_refresh_preview_async()
        self.pacs_show_toast(
            f"已把 {changed} 条规则的动作改为「{PACS_ACTION_LABELS.get(pms_action, pms_action)}」"
        )
        return changed

    def pacs_set_proxy(self, pms_rows: list[int]) -> int:
        """弹窗改代理地址（1 条或多条通用）；留空 = 用方案默认代理。"""
        if not pms_rows:
            return 0
        first = self.pacs_model.pacs_rule_at(pms_rows[0])
        current = first.proxy if first is not None else ""
        scope = f"选中的 {len(pms_rows)} 条规则" if len(pms_rows) > 1 else "这条规则"
        text, ok = QInputDialog.getText(
            self,
            "修改代理地址",
            f"把{scope}的代理地址改为：\n（留空 = 用默认代理地址 {self.pacs_document.default_proxy or '（未设置）'}）",
            text=current,
        )
        if not ok:
            return 0
        changed = self.pacs_model.pacs_batch_set(pms_rows, "proxy", str(text).strip())
        self.pacs_on_model_changed()
        self.pacs_refresh_preview_async()
        self.pacs_show_toast(f"已修改 {changed} 条规则的代理地址")
        return changed

    def pacs_set_note(self, pms_rows: list[int]) -> int:
        """弹窗改备注（1 条或多条通用）。备注只给人看，不影响编译。"""
        if not pms_rows:
            return 0
        first = self.pacs_model.pacs_rule_at(pms_rows[0])
        current = first.note if first is not None else ""
        scope = f"选中的 {len(pms_rows)} 条规则" if len(pms_rows) > 1 else "这条规则"
        text, ok = QInputDialog.getText(self, "修改备注", f"给{scope}写备注：", text=current)
        if not ok:
            return 0
        changed = self.pacs_model.pacs_batch_set(pms_rows, "note", str(text).strip())
        self.pacs_on_model_changed()
        self.pacs_show_toast(f"已修改 {changed} 条规则的备注")
        return changed

    def pacs_duplicate_rules(self, pms_rows: list[int]) -> int:
        """复制选中规则到列表末尾（复制出来的一律启用）。"""
        clones: list[PacsRule] = []
        for row in pms_rows:
            rule = self.pacs_model.pacs_rule_at(row)
            if rule is None:
                continue
            clone = rule.pacs_clone()
            clone.enabled = True
            clones.append(clone)
        if not clones:
            return 0
        insert_at = len(self.pacs_document.rules)
        for offset, clone in enumerate(clones):
            self.pacs_model.pacs_add_rule(clone, insert_at + offset)
        self.pacs_on_model_changed()
        self.pacs_refresh_preview_async()
        self.pacs_show_toast(f"已复制 {len(clones)} 条规则到列表末尾")
        return len(clones)

    # ---- 底部按钮用（弹窗形式，行为与右键菜单一致）
    def pacs_batch_action(self) -> None:
        rows = self.pacs_selected_rows()
        if not rows:
            pacs_info(self, "提示", "请先选中要批量修改的规则（可按住 Ctrl / Shift 多选）。")
            return
        order = [PACS_ACTION_DIRECT, PACS_ACTION_SOCKS5, PACS_ACTION_PROXY, PACS_ACTION_MIXED]
        labels = [PACS_ACTION_LABELS[action] for action in order]
        label, ok = QInputDialog.getItem(
            self, "批量改动作", f"把选中的 {len(rows)} 条规则的动作改为：", labels, 1, False
        )
        if not ok:
            return
        value = {PACS_ACTION_LABELS[action]: action for action in order}.get(label, PACS_ACTION_SOCKS5)
        self.pacs_set_action(rows, value)

    def pacs_batch_proxy(self) -> None:
        rows = self.pacs_selected_rows()
        if not rows:
            pacs_info(self, "提示", "请先选中要批量修改的规则。")
            return
        self.pacs_set_proxy(rows)

    def pacs_batch_enabled(self, pms_enabled: bool) -> None:
        rows = self.pacs_selected_rows()
        if not rows:
            return
        changed = self.pacs_model.pacs_batch_set(rows, "enabled", bool(pms_enabled))
        self.pacs_model.pacs_refresh_all()
        self.pacs_on_model_changed()
        self.pacs_show_toast(f"已{'启用' if pms_enabled else '停用'} {changed} 条规则")

    # ------------------------------------------------------------------ 右键菜单
    def pacs_build_table_menu(self) -> QMenu:
        """按「选中几条」构建不同菜单。

        - 0 条：只给添加 / 全部启停
        - 1 条：单条方案（编辑、改动作、改代理、改备注、复制、启停、上移下移、删除）
        - 多条：批量方案（批量动作子菜单、批量代理、批量备注、批量启停、复制、删除）

        性能约定（实测过）：
            - 条数用 `pacs_selected_count()`（区间累加，O(区间数)），**不构造行号列表**；
            - 行号只在用户真正点菜单项时才取（lambda 里调 `pacs_selected_rows()`），
              因此「右键弹出菜单」在 4000+ 行全选时也是毫秒级。
        拆成独立方法（不 exec），便于冒烟测试直接检查菜单结构。
        """
        count = self.pacs_selected_count()
        menu = QMenu(self)

        if count == 0:
            menu.addAction(self.pacs_make_menu_action(menu, "添加规则…", self.pacs_add_rule))
            menu.addSeparator()
            menu.addAction(
                self.pacs_make_menu_action(menu, "启用全部", lambda: self.pacs_batch_enabled(True))
            )
            menu.addAction(
                self.pacs_make_menu_action(menu, "停用全部", lambda: self.pacs_batch_enabled(False))
            )
            return menu

        single_rule = None
        if count == 1:
            rows_one = self.pacs_selected_rows()
            if rows_one:
                single_rule = self.pacs_model.pacs_rule_at(rows_one[0])

        scope = "这条规则" if count == 1 else f"选中的 {count} 条规则"
        if count == 1:
            menu.addAction(self.pacs_make_menu_action(menu, "编辑这条规则…", self.pacs_edit_rule))
        else:
            menu.addAction(
                self.pacs_make_menu_action(menu, f"批量修改（{count} 条）…", self.pacs_batch_action)
            )

        # 动作子菜单：1 条时勾出当前动作；点击时才去取选中行（延迟取，右键不付代价）
        action_menu = menu.addMenu("修改动作")
        for action in (PACS_ACTION_DIRECT, PACS_ACTION_SOCKS5, PACS_ACTION_PROXY, PACS_ACTION_MIXED):
            item = self.pacs_make_menu_action(
                action_menu,
                PACS_ACTION_LABELS[action],
                lambda checked=False, a=action: self.pacs_set_action(self.pacs_selected_rows(), a),
            )
            if count == 1:
                item.setCheckable(True)
                item.setChecked(single_rule is not None and action == single_rule.action)
            action_menu.addAction(item)
        action_menu.addSeparator()
        action_menu.addAction(
            self.pacs_make_menu_action(action_menu, "弹窗选择…", self.pacs_batch_action)
        )

        menu.addAction(
            self.pacs_make_menu_action(menu, "修改代理地址…", lambda: self.pacs_set_proxy(self.pacs_selected_rows()))
        )
        menu.addAction(
            self.pacs_make_menu_action(menu, "修改备注…", lambda: self.pacs_set_note(self.pacs_selected_rows()))
        )
        menu.addSeparator()
        menu.addAction(
            self.pacs_make_menu_action(
                menu,
                "复制这条规则" if count == 1 else f"复制选中的 {count} 条规则",
                lambda: self.pacs_duplicate_rules(self.pacs_selected_rows()),
            )
        )

        if count == 1:
            if single_rule is not None and single_rule.enabled:
                menu.addAction(
                    self.pacs_make_menu_action(menu, "停用这条规则", lambda: self.pacs_batch_enabled(False))
                )
            else:
                menu.addAction(
                    self.pacs_make_menu_action(menu, "启用这条规则", lambda: self.pacs_batch_enabled(True))
                )
        else:
            menu.addAction(
                self.pacs_make_menu_action(menu, "全部启用", lambda: self.pacs_batch_enabled(True))
            )
            menu.addAction(
                self.pacs_make_menu_action(menu, "全部停用", lambda: self.pacs_batch_enabled(False))
            )

        menu.addSeparator()
        if count == 1:
            menu.addAction(self.pacs_make_menu_action(menu, "上移", lambda: self.pacs_move_rule(-1)))
            menu.addAction(self.pacs_make_menu_action(menu, "下移", lambda: self.pacs_move_rule(1)))
            menu.addSeparator()
        menu.addAction(self.pacs_make_menu_action(menu, f"删除{scope}", self.pacs_remove_rules))
        return menu

    def pacs_show_table_menu(self, pms_pos) -> None:
        # 右键点在「未选中行」上时先把选择切过去（用区间判断，避免全选时构造大量 index）
        index = self.pacs_table.indexAt(pms_pos)
        if index.isValid() and not self.pacs_is_proxy_row_selected(index.row()):
            self.pacs_table.selectRow(index.row())
        menu = self.pacs_build_table_menu()
        try:
            menu.exec(self.pacs_table.viewport().mapToGlobal(pms_pos))
        finally:
            # 必须释放：菜单与里面的 action 都挂在菜单下。不删的话每次右键都在主窗口留下
            # 1 个 QMenu + 19 个 QAction（实测 200 次后构建耗时 1.5ms → 7.4ms）
            menu.deleteLater()

    # ------------------------------------------------------------------ 默认项
    def pacs_on_default_changed(self, *pms_args) -> None:
        """默认动作 / 协议变化。信号会带 index 参数，用 *args 吞掉避免签名不匹配。"""
        self.pacs_document.default_action = self.pacs_default_action_combo.currentData()
        self.pacs_document.default_scheme = self.pacs_scheme_combo.currentData()
        self.pacs_model.pacs_refresh_all()
        self.pacs_on_model_changed()

    def pacs_on_default_proxy_edited(self) -> None:
        text = self.pacs_default_proxy_edit.text().strip()
        if text and not pacs_split_proxy(text)[1]:
            pacs_warn(self, "地址格式不对", "默认代理地址要写成 IP:端口，例如 ***已脱敏***-内网IP:20808")
            self.pacs_default_proxy_edit.setText(self.pacs_document.default_proxy)
            return
        self.pacs_document.default_proxy = text
        self.pacs_model.pacs_refresh_all()
        self.pacs_on_model_changed()

    def pacs_on_search(self, pms_text: str) -> None:
        self.pacs_filter.pacs_set_text(pms_text)

    def pacs_on_model_changed(self, *pms_args) -> None:
        self.pacs_refresh_status()
        self.pacs_schedule_save()
