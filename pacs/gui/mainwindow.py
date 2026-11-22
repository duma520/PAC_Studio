# -*- coding: utf-8 -*-
"""主窗口（骨架）。

职责分工（每个文件都控制在 1000 行以内）：
    mainwindow_ui.py       界面构建：方案行 / 默认项行 / 两个选项卡 / 菜单 / 工具栏 / 托盘
    mainwindow_profiles.py 多方案：刷新、切换、新建、改名、复制、删除
    mainwindow_rules.py    规则表：增删改、上下移、批量、默认项、搜索
    mainwindow_actions.py  动作：编译预览、ZeroOmega 导入导出、应用/还原、设置、关于
    mainwindow.py（本文件） 生命周期：属性装配、保存、状态栏、工作线程、关闭与退出

线程纪律：导入、导出、编译、应用/还原全部走 PacsWorker，主线程只刷 UI；
所有修改都会触发 600ms 防抖保存，切换方案 / 应用 PAC / 关闭窗口时强制立即写盘。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon

from pacs.autostart import PacsWindowsAutoStart
from pacs.constants import PACS_APP_NAME, PACS_LOGGER_NAME, PACS_APP_VERSION
from pacs.gui.mainwindow_actions import PacsActionsMixin
from pacs.gui.mainwindow_profiles import PacsProfilesMixin
from pacs.gui.mainwindow_rules import PacsRulesMixin
from pacs.gui.mainwindow_ui import PacsUiMixin
from pacs.gui.theme import pacs_window_title
from pacs.gui.workers import PacsWorker
from pacs.paths import PacsRuntimePaths
from pacs.pac.compiler import PacsCompileResult
from pacs.pac.model import PacsDocument
from pacs.profiles import PacsProfileStore
from pacs.settings import PacsSettingsManager
from pacs.sysproxy import PacsWindowsSystemProxy

pacs_logger = logging.getLogger(PACS_LOGGER_NAME + ".gui")


class PacsMainWindow(
    PacsUiMixin,
    PacsProfilesMixin,
    PacsRulesMixin,
    PacsActionsMixin,
    QMainWindow,
):
    def __init__(self, pms_paths: PacsRuntimePaths, pms_settings: PacsSettingsManager) -> None:
        super().__init__()
        self.pacs_paths = pms_paths
        self.pacs_settings = pms_settings
        self.pacs_store = PacsProfileStore(pms_paths, pms_settings)
        self.pacs_sysproxy = PacsWindowsSystemProxy()
        self.pacs_autostart = PacsWindowsAutoStart(pms_paths)
        self.pacs_document: PacsDocument = self.pacs_store.pacs_load()
        self.pacs_worker: Optional[PacsWorker] = None
        self.pacs_compile_result: Optional[PacsCompileResult] = None
        self.pacs_tray: Optional[QSystemTrayIcon] = None
        self.pacs_quitting = False
        self.pacs_shutdown_done = False

        self.pacs_save_timer = QTimer(self)
        self.pacs_save_timer.setSingleShot(True)
        self.pacs_save_timer.setInterval(600)
        self.pacs_save_timer.timeout.connect(lambda: self.pacs_save_now(pms_reason="自动保存"))

        self.setWindowTitle(pacs_window_title())
        self.setMinimumSize(980, 660)
        self.pacs_build_ui()
        self.pacs_build_menus()
        self.pacs_build_tray()
        self.pacs_restore_geometry()
        self.pacs_reload_all()
        self.pacs_refresh_status()
        QTimer.singleShot(200, self.pacs_refresh_preview_async)

    # ================================================================== 保存 / 状态
    def pacs_schedule_save(self) -> None:
        self.pacs_save_timer.start()

    def pacs_save_now(self, pms_reason: str = "") -> bool:
        self.pacs_save_timer.stop()
        ok = self.pacs_store.pacs_save(self.pacs_document)
        if not ok:
            pacs_logger.error("保存方案失败（%s）", pms_reason)
            from pacs.gui.widgets import pacs_error

            pacs_error(self, "保存失败", "规则文件写不进去，可能是磁盘满或没有权限。")
            return False
        self.pacs_mark_saved()
        return True

    def pacs_mark_saved(self) -> None:
        """在状态栏留下「已保存 HH:MM:SS」，让用户看得见确实落盘了。"""
        label = getattr(self, "pacs_saved_label", None)
        if label is None:
            return
        label.setText(f"已保存 {time.strftime('%H:%M:%S')}")

    def pacs_save_manual(self) -> None:
        """工具栏 / 菜单 / Ctrl+S 的显式保存。

        平时改动会自动保存（600ms 防抖）；这个按钮是「立即写盘 + 明确告诉我存哪了」，
        给用户确定感，也便于在改动后马上应用 PAC。
        """
        if not self.pacs_save_now("手动保存"):
            return
        path = self.pacs_store.pacs_profile_file(self.pacs_document.name)
        self.pacs_show_toast(f"已保存：{path}" if path else "已保存")

    def pacs_refresh_status(self) -> None:
        self.pacs_stats_label.setText(
            f"{self.pacs_model.pacs_stats_text()} · 方案：{self.pacs_document.name}"
        )
        self.pacs_windows_label.setText(
            self.pacs_sysproxy.pacs_describe(self.pacs_paths.prt_pac_file)
        )

    # ================================================================== 工作线程
    def pacs_start_worker(self, pms_task, pms_on_done) -> PacsWorker:
        worker = PacsWorker(pms_task, self)
        worker.sig_progress.connect(self.pacs_on_worker_progress)
        worker.sig_done.connect(pms_on_done)
        worker.sig_error.connect(self.pacs_on_worker_error)
        worker.finished.connect(lambda: setattr(self, "pacs_worker", None))
        worker.start()
        return worker

    def pacs_on_worker_progress(self, pms_percent: int, pms_text: str) -> None:
        self.pacs_progress.pacs_update(pms_percent, pms_text)

    def pacs_on_worker_error(self, pms_message: str) -> None:
        self.pacs_progress.pacs_hide_after(400)
        from pacs.gui.widgets import pacs_error

        pacs_error(self, "操作失败", pms_message)

    def pacs_show_toast(self, pms_text: str) -> None:
        self.statusBar().showMessage(pms_text, 4000)

    # ================================================================== 退出
    def pacs_quit(self) -> None:
        """托盘菜单「退出」/菜单「退出」的入口。

        注意：**不能只调 self.close()**。用户点过窗口 X 之后，窗口已经被 hide() 到托盘，
        此时 close() 关掉的是一个隐藏窗口，Qt 不会发出 lastWindowClosed，
        `quitOnLastWindowClosed` 就不生效 —— 事件循环永不返回，进程一直挂着。
        所以这里显式走一遍清理并 `QApplication.quit()`。
        """
        self.pacs_quitting = True
        self.pacs_do_shutdown()
        self.close()
        app = QApplication.instance()
        if app is not None:
            # 等托盘菜单收起后再退出，避免在菜单的嵌套事件循环里退出导致不干净
            QTimer.singleShot(0, app.quit)

    def pacs_do_shutdown(self) -> None:
        """幂等的退出清理：存盘 → 存窗口几何 → 等工作线程 → 还原系统代理 → 销毁托盘。"""
        if self.pacs_shutdown_done:
            return
        self.pacs_shutdown_done = True
        self.pacs_save_timer.stop()
        if not self.pacs_store.pacs_save(self.pacs_document):
            pacs_logger.error("退出前保存方案失败")
        self.pacs_save_geometry()
        self.pacs_shutdown_workers()
        if self.pacs_settings.pacs_get_bool("system_proxy.restore_on_exit", True) and self.pacs_settings.pacs_get_bool(
            "system_proxy.backup_saved", False
        ):
            self.pacs_sysproxy.pacs_restore_from_settings(
                self.pacs_settings, self.pacs_paths.prt_data_dir / "system_proxy_backup.json"
            )
        self.pacs_dispose_tray()

    def pacs_shutdown_workers(self, pms_timeout_ms: int = 2000) -> None:
        """等工作线程收尾。

        不等的话，进程退出时 Qt 会报 `QThread: Destroyed while thread is still running`，
        严重时进程挂住；如果线程正在写 PAC 文件/注册表，还可能留下半截状态。
        正常任务（编译 0.3s、导入 1s、应用 0.1s）都能在 2 秒内结束。
        """
        worker = self.pacs_worker
        self.pacs_worker = None
        if worker is None:
            return
        # 先断开回调：退出过程中 worker 恰好完成时，排队的「应用成功/失败」对话框
        # 会弹出来把退出流程卡住（模态框会吃掉 quit）
        for signal in (worker.sig_done, worker.sig_error, worker.sig_progress):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        try:
            if worker.isRunning():
                worker.requestInterruption()
                if not worker.wait(pms_timeout_ms):
                    pacs_logger.warning("工作线程 %d ms 内没有结束，继续退出", pms_timeout_ms)
        except RuntimeError:
            # 底层 C++ 对象已析构（极少数重复退出场景），不用处理
            pass

    def pacs_dispose_tray(self) -> None:
        """彻底销毁托盘图标。

        只 hide() 不够：Windows 通知区域会留下「幽灵图标」，用户会以为程序还在跑。
        这里连同上下文菜单一起断开并延后删除。
        """
        tray = self.pacs_tray
        self.pacs_tray = None
        if tray is None:
            return
        try:
            tray.hide()
            tray.setContextMenu(None)
            tray.setVisible(False)
            tray.deleteLater()
        except RuntimeError:
            pass

    def closeEvent(self, pms_event: QCloseEvent) -> None:  # noqa: N802 Qt 命名
        if (
            not self.pacs_quitting
            and self.pacs_tray is not None
            and self.pacs_settings.pacs_get_bool("ui.close_to_tray", True)
        ):
            pms_event.ignore()
            self.hide()
            self.pacs_show_toast("已最小化到托盘，右键托盘图标可退出")
            return
        self.pacs_do_shutdown()
        pms_event.accept()
        app = QApplication.instance()
        if app is not None:
            # 不依赖 lastWindowClosed（窗口可能早已隐藏），显式退出事件循环
            QTimer.singleShot(0, app.quit)
