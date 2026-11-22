# -*- coding: utf-8 -*-
"""PAC 分流工作室（PAC Studio）· 主入口。

这是**主程序文件**（最终更新版）：所有启动路径都从这里进。

命令行：
    python PAC_Studio.py                     启动图形界面
    python PAC_Studio.py --apply-pac --silent  静默编译并让 Windows 走 PAC（开机自启用）
    python PAC_Studio.py --restore             还原原来的系统代理设置
    python PAC_Studio.py --compile-only OUT    只编译当前方案到指定文件
    python PAC_Studio.py --version             打印版本
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path
from typing import Optional

from pacs.constants import (
    PACS_APP_NAME,
    PACS_APP_NAME_EN,
    PACS_APP_VERSION,
    PACS_COMPILE_OPTIMIZED,
    PACS_LOGGER_NAME,
)
from pacs.paths import PacsRuntimePaths
from pacs.settings import PacsSettingsManager

pacs_logger = logging.getLogger(PACS_LOGGER_NAME)


# --------------------------------------------------------------------------------------
# 日志
# --------------------------------------------------------------------------------------
def pacs_setup_logging(pms_paths: PacsRuntimePaths, pms_level: str = "INFO") -> None:
    level = getattr(logging, str(pms_level or "INFO").upper(), logging.INFO)
    root = logging.getLogger(PACS_LOGGER_NAME)
    root.setLevel(level)
    root.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    try:
        handler = logging.handlers.RotatingFileHandler(
            pms_paths.prt_log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(formatter)
        handler.setLevel(level)
        root.addHandler(handler)
    except OSError:
        pass
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    stream.setLevel(level)
    root.addHandler(stream)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def pacs_cli_apply(pms_paths: PacsRuntimePaths, pms_settings: PacsSettingsManager) -> int:
    """静默编译 + 应用。开机自启走这条路，不弹任何窗。"""
    from pacs.pac.compiler import pacs_compile
    from pacs.profiles import PacsProfileStore
    from pacs.sysproxy import PacsWindowsSystemProxy
    from pacs.utils import pacs_atomic_write_text

    store = PacsProfileStore(pms_paths, pms_settings)
    document = store.pacs_load()
    mode = pms_settings.pacs_get_str("pac.compile_mode", PACS_COMPILE_OPTIMIZED)
    compiled = pacs_compile(
        document, mode, pms_settings.pacs_get_bool("pac.escape_unicode", True)
    )
    pac_file = pms_paths.prt_pac_file
    try:
        pacs_atomic_write_text(pac_file, compiled.text)
    except OSError as exc:
        pacs_logger.error("写入 PAC 失败：%s", exc)
        return 2
    sysproxy = PacsWindowsSystemProxy()
    if not pms_settings.pacs_get_bool("system_proxy.backup_saved", False):
        sysproxy.pacs_backup_to_settings(
            pms_settings, pms_paths.prt_data_dir / "system_proxy_backup.json"
        )
    ok = sysproxy.pacs_enable_pac_file(pac_file)
    pacs_logger.info(
        "静默应用%s：%s（%s）", "成功" if ok else "失败", pac_file, compiled.pacs_summary()
    )
    return 0 if ok else 1


def pacs_cli_restore(pms_paths: PacsRuntimePaths, pms_settings: PacsSettingsManager) -> int:
    from pacs.sysproxy import PacsWindowsSystemProxy

    sysproxy = PacsWindowsSystemProxy()
    ok = sysproxy.pacs_restore_from_settings(
        pms_settings, pms_paths.prt_data_dir / "system_proxy_backup.json"
    )
    pacs_logger.info("还原系统代理：%s", "成功" if ok else "无备份或失败")
    return 0 if ok else 1


def pacs_cli_compile(pms_paths: PacsRuntimePaths, pms_settings: PacsSettingsManager, pms_out: str) -> int:
    from pacs.pac.compiler import pacs_compile
    from pacs.profiles import PacsProfileStore
    from pacs.utils import pacs_atomic_write_text

    store = PacsProfileStore(pms_paths, pms_settings)
    document = store.pacs_load()
    compiled = pacs_compile(
        document,
        pms_settings.pacs_get_str("pac.compile_mode", PACS_COMPILE_OPTIMIZED),
        pms_settings.pacs_get_bool("pac.escape_unicode", True),
    )
    try:
        pacs_atomic_write_text(Path(pms_out), compiled.text)
    except OSError as exc:
        pacs_logger.error("写入失败：%s", exc)
        return 2
    print(compiled.pacs_summary())
    return 0


# --------------------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------------------
def pacs_run_gui(pms_paths: PacsRuntimePaths, pms_settings: PacsSettingsManager) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from pacs.gui.mainwindow import PacsMainWindow
    from pacs.gui.theme import pacs_apply_app_font, pacs_window_title
    from pacs.gui.widgets import pacs_error

    app = QApplication(sys.argv)
    app.setApplicationName(PACS_APP_NAME_EN)
    app.setApplicationDisplayName(PACS_APP_NAME)
    app.setOrganizationName(PACS_APP_NAME_EN)
    family = pacs_apply_app_font(app)
    pacs_logger.info("界面字体：%s", family or "系统默认")

    window = PacsMainWindow(pms_paths, pms_settings)
    window.setWindowTitle(pacs_window_title())
    if pms_paths.prt_icon_exists():
        window.setWindowIcon(window.pacs_app_icon())

    def pms_excepthook(pms_type, pms_value, pms_tb) -> None:  # noqa: ANN001
        text = "".join(traceback.format_exception(pms_type, pms_value, pms_tb))
        pacs_logger.error("未捕获异常：\n%s", text)
        try:
            QMessageBox.critical(
                window,
                "程序出错",
                f"发生了未处理的错误，已写入日志：\n{pms_paths.prt_log_file}\n\n{pms_value}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = pms_excepthook
    window.show()
    return int(app.exec())


# --------------------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------------------
def pacs_parse_args(pms_argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="PAC_Studio.py",
        description=f"{PACS_APP_NAME} v{PACS_APP_VERSION} · 编辑 PAC、让 Windows 走 PAC、与 ZeroOmega 互转",
    )
    parser.add_argument("--base", default="", help="强制指定项目主目录（调试用）")
    parser.add_argument("--apply-pac", action="store_true", help="静默编译并应用 PAC 后退出")
    parser.add_argument("--restore", action="store_true", help="还原原来的系统代理设置后退出")
    parser.add_argument("--compile-only", default="", metavar="OUT", help="只编译当前方案到指定文件")
    parser.add_argument("--silent", action="store_true", help="不输出到控制台")
    parser.add_argument("--version", action="store_true", help="打印版本号")
    return parser.parse_args(pms_argv)


def main(pms_argv: Optional[list[str]] = None) -> int:
    args = pacs_parse_args(pms_argv)
    if args.version:
        print(f"{PACS_APP_NAME} v{PACS_APP_VERSION}")
        return 0

    base = Path(args.base) if args.base else None
    paths = PacsRuntimePaths(base)
    paths.prt_ensure_dirs()
    settings = PacsSettingsManager(paths)
    pacs_setup_logging(paths, settings.pacs_get_str("log.level", "INFO"))
    pacs_logger.info("启动 %s v%s（主目录 %s）", PACS_APP_NAME, PACS_APP_VERSION, paths.pacs_root)

    if args.apply_pac:
        return pacs_cli_apply(paths, settings)
    if args.restore:
        return pacs_cli_restore(paths, settings)
    if args.compile_only:
        return pacs_cli_compile(paths, settings, args.compile_only)
    return pacs_run_gui(paths, settings)


if __name__ == "__main__":
    raise SystemExit(main())
