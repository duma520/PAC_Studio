# -*- coding: utf-8 -*-
"""开机自启（仅「开机后自动应用 PAC」，不常驻托盘）。

写 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`，命令形如：
    源码运行：`"D:\\...\\pythonw.exe" "G:\\...\\PAC_Studio.py" --apply-pac --silent`
    打包运行：`"G:\\...\\PAC_Studio.exe" --apply-pac --silent`
只写当前用户，不需要管理员权限。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from pacs.constants import PACS_APP_NAME, PACS_IS_WINDOWS, PACS_LOGGER_NAME
from pacs.paths import PacsRuntimePaths

pacs_logger = logging.getLogger(PACS_LOGGER_NAME + ".autostart")


class PacsWindowsAutoStart:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "PAC_Studio_AutoApply"

    def __init__(self, pms_paths: PacsRuntimePaths, pms_logger: Optional[logging.Logger] = None) -> None:
        self.pacs_paths = pms_paths
        self.pacs_logger = pms_logger or pacs_logger

    def pacs_command(self) -> str:
        """拼出开机执行的命令行（含引号，路径带空格也安全）。"""
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).resolve()
            return f'"{exe}" --apply-pac --silent'
        main_script = self.pacs_paths.prt_main_script
        python = Path(sys.executable).resolve()
        pythonw = python.with_name("pythonw.exe")
        launcher = pythonw if pythonw.is_file() else python
        return f'"{launcher}" "{main_script}" --apply-pac --silent'

    def pacs_is_enabled(self) -> bool:
        if not PACS_IS_WINDOWS:
            return False
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as key:
                value, _kind = winreg.QueryValueEx(key, self.VALUE_NAME)
                return bool(str(value or "").strip())
        except FileNotFoundError:
            return False
        except OSError as exc:
            self.pacs_logger.warning("读取开机自启失败：%s", exc)
            return False

    def pacs_set_enabled(self, pms_enabled: bool) -> bool:
        if not PACS_IS_WINDOWS:
            return False
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                if pms_enabled:
                    winreg.SetValueEx(key, self.VALUE_NAME, 0, winreg.REG_SZ, self.pacs_command())
                else:
                    try:
                        winreg.DeleteValue(key, self.VALUE_NAME)
                    except FileNotFoundError:
                        pass
            self.pacs_logger.info("开机自启已%s", "启用" if pms_enabled else "关闭")
            return True
        except OSError as exc:
            self.pacs_logger.error("设置开机自启失败：%s", exc)
            return False

    def pacs_describe(self) -> str:
        if self.pacs_is_enabled():
            return f"{PACS_APP_NAME}：开机后自动应用 PAC（已启用）"
        return "开机自启：未启用"
