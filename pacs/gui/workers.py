# -*- coding: utf-8 -*-
"""工作线程：所有可能卡住界面的操作（导入 / 导出 / 编译 / 应用 PAC）都走这里。

约定：
    - task 是一个可调用对象，签名 `task(progress) -> result`，其中
      `progress(percent:int, text:str)` 可以在任务内部任意调用；
    - 结果通过 Qt 信号回到主线程（跨线程 emit 由 Qt 排队，线程安全）；
    - 异常统一转成 `sig_error` 的字符串，绝不静默吞掉。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QThread, Signal

from pacs.constants import PACS_APP_NAME


class PacsWorker(QThread):
    sig_progress = Signal(int, str)
    sig_done = Signal(object)
    sig_error = Signal(str)

    def __init__(self, pms_task: Callable[[Callable[[int, str], None]], Any], pms_parent: Optional[Any] = None) -> None:
        super().__init__(pms_parent)
        self.pacs_task = pms_task
        self.pacs_result: Any = None

    def run(self) -> None:  # noqa: D401 Qt 线程入口
        try:
            self.pacs_result = self.pacs_task(self.sig_progress.emit)
        except Exception as exc:  # noqa: BLE001 线程里任何异常都要变成提示，不能崩进程
            self.sig_error.emit(f"{PACS_APP_NAME}：{type(exc).__name__}: {exc}")
            return
        self.sig_done.emit(self.pacs_result)
