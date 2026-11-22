# -*- coding: utf-8 -*-
"""主窗口 · 界面构建（mixin）。

只负责「长什么样」：方案行、默认项行、两个选项卡、菜单栏、工具栏、托盘。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QSystemTrayIcon,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from pacs.constants import (
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_APP_NAME,
    PACS_APP_VERSION,
)
from pacs.gui.rule_filter import PacsRuleFilterProxy
from pacs.gui.rule_model import PacsRuleTableModel
from pacs.gui.widgets import PacsProgressBar, pacs_make_hint_label


class PacsUiMixin:
    """依赖宿主窗口：pacs_paths / pacs_settings / pacs_document / pacs_model 等属性。"""

    # ================================================================== 主布局
    def pacs_build_ui(self) -> None:
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(6)

        # ---- 方案行 ----
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("方案："))
        self.pacs_profile_combo = QComboBox()
        self.pacs_profile_combo.setMinimumWidth(200)
        self.pacs_profile_combo.currentIndexChanged.connect(self.pacs_on_profile_changed)
        profile_row.addWidget(self.pacs_profile_combo)
        for text, slot in (
            ("新建", self.pacs_create_profile),
            ("改名", self.pacs_rename_profile),
            ("复制", self.pacs_duplicate_profile),
            ("删除", self.pacs_delete_profile),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            profile_row.addWidget(button)
        profile_row.addStretch(1)
        profile_row.addWidget(QLabel("搜索："))
        self.pacs_search_edit = QLineEdit()
        self.pacs_search_edit.setPlaceholderText("按域名 / 备注 / 类型筛选…")
        self.pacs_search_edit.setClearButtonEnabled(True)
        self.pacs_search_edit.setMaximumWidth(240)
        self.pacs_search_edit.textChanged.connect(self.pacs_on_search)
        profile_row.addWidget(self.pacs_search_edit)
        layout.addLayout(profile_row)

        # ---- 默认项行 ----
        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("没命中任何规则时："))
        self.pacs_default_action_combo = QComboBox()
        self.pacs_default_action_combo.addItem("默认直连", "direct")
        self.pacs_default_action_combo.addItem("默认走代理", "proxy")
        self.pacs_default_action_combo.currentIndexChanged.connect(self.pacs_on_default_changed)
        default_row.addWidget(self.pacs_default_action_combo)

        default_row.addWidget(QLabel("协议："))
        self.pacs_scheme_combo = QComboBox()
        self.pacs_scheme_combo.addItem("SOCKS5", PACS_ACTION_SOCKS5)
        self.pacs_scheme_combo.addItem("HTTP 代理", PACS_ACTION_PROXY)
        self.pacs_scheme_combo.addItem("混合", PACS_ACTION_MIXED)
        self.pacs_scheme_combo.currentIndexChanged.connect(self.pacs_on_default_changed)
        default_row.addWidget(self.pacs_scheme_combo)

        default_row.addWidget(QLabel("默认代理地址："))
        self.pacs_default_proxy_edit = QLineEdit()
        self.pacs_default_proxy_edit.setMinimumWidth(200)
        self.pacs_default_proxy_edit.setPlaceholderText("IP:端口，例如 ***已脱敏***-内网IP:20808")
        self.pacs_default_proxy_edit.editingFinished.connect(self.pacs_on_default_proxy_edited)
        default_row.addWidget(self.pacs_default_proxy_edit)
        default_row.addStretch(1)
        layout.addLayout(default_row)

        # ---- 选项卡 ----
        self.pacs_tabs = QTabWidget()
        self.pacs_tabs.addTab(self.pacs_build_rules_tab(), "规则表")
        self.pacs_tabs.addTab(self.pacs_build_script_tab(), "PAC 脚本")
        layout.addWidget(self.pacs_tabs, 1)
        self.setCentralWidget(central)

        # ---- 状态栏 ----
        status = self.statusBar()
        self.pacs_stats_label = QLabel("")
        self.pacs_saved_label = QLabel("")
        self.pacs_windows_label = QLabel("")
        self.pacs_progress = PacsProgressBar()
        status.addWidget(self.pacs_stats_label, 1)
        status.addPermanentWidget(self.pacs_saved_label)
        status.addPermanentWidget(self.pacs_windows_label)
        status.addPermanentWidget(self.pacs_progress)

    def pacs_build_rules_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self.pacs_model = PacsRuleTableModel(self.pacs_document)
        self.pacs_filter = PacsRuleFilterProxy(self)
        self.pacs_filter.setSourceModel(self.pacs_model)
        self.pacs_model.dataChanged.connect(self.pacs_on_model_changed)
        self.pacs_model.rowsInserted.connect(self.pacs_on_model_changed)
        self.pacs_model.rowsRemoved.connect(self.pacs_on_model_changed)

        self.pacs_table = QTableView()
        self.pacs_table.setModel(self.pacs_filter)
        self.pacs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.pacs_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.pacs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pacs_table.setAlternatingRowColors(True)
        self.pacs_table.setWordWrap(False)
        self.pacs_table.doubleClicked.connect(lambda _index: self.pacs_edit_rule())
        self.pacs_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pacs_table.customContextMenuRequested.connect(self.pacs_show_table_menu)
        header = self.pacs_table.horizontalHeader()
        for column, mode in (
            (PacsRuleTableModel.COL_ENABLED, QHeaderView.ResizeMode.ResizeToContents),
            (PacsRuleTableModel.COL_INDEX, QHeaderView.ResizeMode.ResizeToContents),
            (PacsRuleTableModel.COL_MATCH, QHeaderView.ResizeMode.ResizeToContents),
            (PacsRuleTableModel.COL_CONTENT, QHeaderView.ResizeMode.Stretch),
            (PacsRuleTableModel.COL_ACTION, QHeaderView.ResizeMode.ResizeToContents),
            (PacsRuleTableModel.COL_PROXY, QHeaderView.ResizeMode.ResizeToContents),
            (PacsRuleTableModel.COL_NOTE, QHeaderView.ResizeMode.Stretch),
        ):
            header.setSectionResizeMode(column, mode)
        self.pacs_table.verticalHeader().setVisible(False)
        layout.addWidget(self.pacs_table, 1)

        button_row = QHBoxLayout()
        for text, slot in (
            ("+ 添加规则", self.pacs_add_rule),
            ("编辑", self.pacs_edit_rule),
            ("删除", self.pacs_remove_rules),
            ("上移", lambda: self.pacs_move_rule(-1)),
            ("下移", lambda: self.pacs_move_rule(1)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            button_row.addWidget(button)
        button_row.addSpacing(12)
        for text, slot in (
            ("批量改动作", self.pacs_batch_action),
            ("批量改代理", self.pacs_batch_proxy),
            ("启用选中", lambda: self.pacs_batch_enabled(True)),
            ("停用选中", lambda: self.pacs_batch_enabled(False)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            button_row.addWidget(button)
        button_row.addStretch(1)
        button_row.addSpacing(12)
        save_button = QPushButton("保存")
        save_button.setToolTip("立即把当前方案写盘（平时改动会自动保存，这里是手动确认）")
        save_button.clicked.connect(self.pacs_save_manual)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)
        layout.addWidget(pacs_make_hint_label(
            "规则<b>从上往下</b>判断，先命中先生效。双击一行可编辑；按住 Ctrl / Shift 可多选后批量改。"
            "代理地址留空表示使用上面的「默认代理地址」。"
        ))
        return page

    def pacs_build_script_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        layout.addWidget(pacs_make_hint_label(
            "这里是<b>编译产物</b>（只读预览）。想直接手写脚本，点「手写编辑」；"
            "手写完点「解析回规则表」，本程序会尽力把脚本还原成规则（识别不了的部分会提示，不会清空规则）。"
        ))
        self.pacs_script_edit = QPlainTextEdit()
        self.pacs_script_edit.setReadOnly(True)
        self.pacs_script_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.pacs_script_edit.setPlaceholderText("点「编译预览」生成脚本，或点「手写编辑」直接写。")
        layout.addWidget(self.pacs_script_edit, 1)

        row = QHBoxLayout()
        for text, slot in (
            ("编译预览", self.pacs_compile_preview),
            ("手写编辑", self.pacs_toggle_script_editable),
            ("解析回规则表", self.pacs_parse_script_back),
            ("另存为 .pac", self.pacs_save_pac_as),
            ("打开 PAC 所在目录", lambda: self.pacs_open_data_dir()),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    # ================================================================== 菜单 / 工具栏
    def pacs_build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("文件(&F)")
        self.pacs_add_action(file_menu, "导入 ZeroOmega PAC…", self.pacs_import_omega, "Ctrl+I")
        self.pacs_add_action(file_menu, "导出为 ZeroOmega PAC…", self.pacs_export_omega, "Ctrl+E")
        file_menu.addSeparator()
        self.pacs_add_action(file_menu, "保存当前方案", self.pacs_save_manual, "Ctrl+S")
        self.pacs_add_action(file_menu, "导出方案为 JSON…", self.pacs_export_bundle)
        file_menu.addSeparator()
        self.pacs_add_action(file_menu, "退出", self.close, "Ctrl+Q")

        edit_menu = bar.addMenu("编辑(&E)")
        self.pacs_add_action(edit_menu, "添加规则", self.pacs_add_rule, "Ctrl+N")
        self.pacs_add_action(edit_menu, "编辑选中", self.pacs_edit_rule)
        self.pacs_add_action(edit_menu, "删除选中", self.pacs_remove_rules, "Delete")

        tool_menu = bar.addMenu("工具(&T)")
        self.pacs_add_action(tool_menu, "编译预览", self.pacs_compile_preview, "F5")
        self.pacs_add_action(tool_menu, "应用到 Windows（走 PAC）", self.pacs_apply_to_windows, "F9")
        self.pacs_add_action(tool_menu, "还原原来的系统代理", self.pacs_restore_windows)
        tool_menu.addSeparator()
        self.pacs_add_action(tool_menu, "设置…", self.pacs_open_settings)

        help_menu = bar.addMenu("帮助(&H)")
        self.pacs_add_action(help_menu, "说明 / 关于", self.pacs_show_about)

        toolbar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        # 保存放最前面：工具栏的不带快捷键，Ctrl+S 交给菜单里那个 action，避免快捷键冲突
        toolbar.addAction(self.pacs_make_action("保存", self.pacs_save_manual))
        toolbar.addSeparator()
        for text, slot in (
            ("导入 ZeroOmega", self.pacs_import_omega),
            ("导出 ZeroOmega", self.pacs_export_omega),
            ("编译预览", self.pacs_compile_preview),
            ("应用到 Windows", self.pacs_apply_to_windows),
            ("还原原设置", self.pacs_restore_windows),
            ("设置", self.pacs_open_settings),
        ):
            toolbar.addAction(self.pacs_make_action(text, slot))

    def pacs_add_action(self, pms_menu: QMenu, pms_text: str, pms_slot, pms_shortcut: str = "") -> QAction:
        action = self.pacs_make_action(pms_text, pms_slot, pms_shortcut)
        pms_menu.addAction(action)
        return action

    def pacs_make_action(self, pms_text: str, pms_slot, pms_shortcut: str = "") -> QAction:
        """构造已连好槽的 QAction（菜单栏 / 工具栏用，parent 是主窗口，长期存在）。

        注意：PySide6 的 QAction 构造函数**不接受** `triggered=` 关键字（那是 Qt Designer / PyQt
        的写法），传了会在运行期抛 TypeError。所以一律先构造再 connect。
        """
        action = QAction(pms_text, self)
        if pms_shortcut:
            action.setShortcut(pms_shortcut)
        action.triggered.connect(pms_slot)
        return action

    def pacs_make_menu_action(self, pms_menu: QMenu, pms_text: str, pms_slot) -> QAction:
        """构造挂在「弹出菜单」下的 QAction。

        和 `pacs_make_action` 的区别就是 parent：这里挂菜单。右键菜单每次弹出都重建，
        必须让 action 跟着菜单一起销毁，否则主窗口的子对象会随右键次数无限增长
        （实测 200 次右键后累积 400 个 QMenu、3800 个 QAction，构建耗时翻 5 倍）。
        """
        action = QAction(pms_text, pms_menu)
        action.triggered.connect(pms_slot)
        return action

    # ================================================================== 托盘
    def pacs_build_tray(self) -> None:
        if not self.pacs_settings.pacs_get_bool("ui.tray_enabled", True):
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.pacs_app_icon(), self)
        tray.setToolTip(f"{PACS_APP_NAME} v{PACS_APP_VERSION}")
        menu = QMenu(self)
        menu.addAction(self.pacs_make_action("显示主窗口", self.pacs_show_window))
        menu.addAction(self.pacs_make_action("应用到 Windows（走 PAC）", self.pacs_apply_to_windows))
        menu.addAction(self.pacs_make_action("还原原来的系统代理", self.pacs_restore_windows))
        menu.addSeparator()
        menu.addAction(self.pacs_make_action("退出", self.pacs_quit))
        tray.setContextMenu(menu)
        tray.activated.connect(self.pacs_on_tray_activated)
        tray.show()
        self.pacs_tray = tray

    def pacs_app_icon(self) -> QIcon:
        """规则：icon.ico 存在才用，不存在退回系统标准图标（绝不因缺文件崩溃）。"""
        if self.pacs_paths.prt_icon_exists():
            icon = QIcon(str(self.pacs_paths.prt_icon_file))
            if not icon.isNull():
                return icon
        return self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    def pacs_on_tray_activated(self, pms_reason) -> None:
        if pms_reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.pacs_show_window()

    def pacs_show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def pacs_rebuild_tray(self) -> None:
        if self.pacs_tray is not None:
            self.pacs_tray.hide()
            self.pacs_tray = None
        self.pacs_build_tray()

    # ================================================================== 窗口几何
    def pacs_restore_geometry(self) -> None:
        raw = self.pacs_settings.pacs_get_str("ui.window_geometry", "")
        if not raw:
            return
        try:
            from base64 import b64decode

            self.restoreGeometry(b64decode(raw.encode("ascii")))
        except Exception:  # noqa: BLE001
            pass

    def pacs_save_geometry(self) -> None:
        try:
            from base64 import b64encode

            self.pacs_settings.psm_set(
                "ui.window_geometry", b64encode(bytes(self.saveGeometry())).decode("ascii")
            )
        except Exception:  # noqa: BLE001
            pass
