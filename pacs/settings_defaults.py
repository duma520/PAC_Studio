# -*- coding: utf-8 -*-
"""设置默认值（**唯一真源**）。

纪律（沿用 Proxy_Manager_Studio v1.9.x 踩过的坑）：
    新增任何设置键，都必须先加进 `PACS_SETTINGS_DEFAULTS`。
    否则它只会被写进文件、读的时候被当成未知键丢弃，表现为「存了但读不到」。
"""

from __future__ import annotations

from typing import Any

from pacs.constants import (
    PACS_COMPILE_OPTIMIZED,
    PACS_DEFAULT_PROXY_ADDRESS,
    PACS_DEFAULT_PROXY_SCHEME,
    PACS_ACTION_SOCKS5,
)

#: 设置键 → 默认值。值类型即该键的期望类型（bool / int / str）。
PACS_SETTINGS_DEFAULTS: dict[str, Any] = {
    # ---- 应用 ----
    "app.version_last_seen": "",
    "app.first_run_done": False,
    # ---- 默认外部代理 ----
    "proxy.default_address": PACS_DEFAULT_PROXY_ADDRESS,
    "proxy.default_scheme": PACS_DEFAULT_PROXY_SCHEME,
    "proxy.mixed_add_direct_fallback": False,
    # ---- 编译 ----
    "pac.compile_mode": PACS_COMPILE_OPTIMIZED,
    "pac.output_file": "",              # 空 = data/pac_current.pac
    "pac.escape_unicode": False,
    # ---- 系统代理 ----
    "system_proxy.enabled": False,
    "system_proxy.backup_saved": False,
    "system_proxy.original_enable": 0,
    "system_proxy.original_server": "",
    "system_proxy.original_bypass": "",
    "system_proxy.original_auto_config_url": "",
    "system_proxy.restore_on_exit": True,
    # ---- 方案（方案列表与当前方案的真源是 data/profiles.json，不在这里重复存） ----
    "profiles.last_import_dir": "",
    # ---- 界面 ----
    "ui.window_geometry": "",
    "ui.window_state": "",
    "ui.splitter_sizes": "",
    "ui.tray_enabled": True,
    "ui.close_to_tray": True,
    "ui.show_preview": True,
    "ui.last_import_dir": "",
    # ---- 开机自启 / 自动应用 ----
    "autostart.enabled": False,
    # ---- ZeroOmega ----
    "omega.escape_unicode": True,
    "omega.last_import_path": "",
    "omega.export_style": "compatible",   # compatible=同构 +Master 风格 / flat=直返
    # ---- 日志 ----
    "log.level": "INFO",
}

#: 允许的枚举值（越界时回落到默认，避免脏配置把界面搞崩）
PACS_SETTINGS_ENUMS: dict[str, tuple[str, ...]] = {
    "proxy.default_scheme": ("PROXY", PACS_ACTION_SOCKS5, "MIXED"),
    "pac.compile_mode": ("optimized", "readable"),
    "omega.export_style": ("compatible", "flat"),
    "log.level": ("DEBUG", "INFO", "WARNING", "ERROR"),
}


def pacs_settings_default(pms_key: str, pms_fallback: Any = None) -> Any:
    return PACS_SETTINGS_DEFAULTS.get(pms_key, pms_fallback)


def pacs_is_known_key(pms_key: str) -> bool:
    return pms_key in PACS_SETTINGS_DEFAULTS


def pacs_coerce(pms_key: str, pms_value: Any) -> Any:
    """按默认值类型把配置值收敛到合法范围（脏数据容错）。"""
    default = PACS_SETTINGS_DEFAULTS.get(pms_key)
    if default is None and pms_key not in PACS_SETTINGS_DEFAULTS:
        return pms_value
    if isinstance(default, bool):
        if isinstance(pms_value, bool):
            return pms_value
        if isinstance(pms_value, (int, float)):
            return bool(pms_value)
        text = str(pms_value).strip().lower()
        return text in ("1", "true", "yes", "on", "是")
    if isinstance(default, int):
        try:
            return int(pms_value)
        except (TypeError, ValueError):
            return default
    text = "" if pms_value is None else str(pms_value)
    allowed = PACS_SETTINGS_ENUMS.get(pms_key)
    if allowed and text not in allowed:
        return default
    return text
