# -*- coding: utf-8 -*-
"""设置管理器：加载 / 读取 / 实时落盘。

设计要点：
    - **每次 set 立即原子写**。设置文件只有几 KB，写入成本可忽略，换来「改完就落盘、
      断电/崩溃不丢、重启自动加载」的确定性（项目规则：所有设置实时自动保存）。
    - 加载时按 `PACS_SETTINGS_DEFAULTS` 收敛类型与枚举；未知键保留在内存但不参与读取，
      并可通过 `pacs_unknown_keys()` 查出来（便于发现拼写错误）。
    - 损坏文件改名 `.bad-<时间戳>` 后重建，绝不静默丢用户数据。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Optional

from pacs.constants import PACS_APP_NAME, PACS_APP_VERSION, PACS_LOGGER_NAME
from pacs.paths import PacsRuntimePaths
from pacs.settings_defaults import (
    PACS_SETTINGS_DEFAULTS,
    pacs_coerce,
    pacs_is_known_key,
)
from pacs.utils import pacs_atomic_write_text, pacs_json_dump, pacs_json_load

pacs_logger = logging.getLogger(PACS_LOGGER_NAME + ".settings")


class PacsSettingsManager:
    """json 设置的后台读写。线程安全（所有写操作走同一把锁）。"""

    def __init__(self, pms_paths: PacsRuntimePaths) -> None:
        self.pacs_paths = pms_paths
        self.pacs_lock = threading.RLock()
        self.pacs_data: dict[str, Any] = dict(PACS_SETTINGS_DEFAULTS)
        self.pacs_unknown: dict[str, Any] = {}
        self.pacs_load()

    # ------------------------------------------------------------------ 加载 / 保存
    def pacs_load(self) -> None:
        path: Path = self.pacs_paths.prt_settings_file
        raw = pacs_json_load(path, pms_default={})
        if not isinstance(raw, dict):
            raw = {}
        data: dict[str, Any] = dict(PACS_SETTINGS_DEFAULTS)
        unknown: dict[str, Any] = {}
        for key, value in raw.items():
            if pacs_is_known_key(key):
                data[key] = pacs_coerce(key, value)
            else:
                unknown[key] = value
        with self.pacs_lock:
            self.pacs_data = data
            self.pacs_unknown = unknown
        # 版本迁移：记录上次版本，便于以后做一次性迁移
        if data.get("app.version_last_seen") != PACS_APP_VERSION:
            data["app.version_last_seen"] = PACS_APP_VERSION
            self.pacs_save()

    def pacs_save(self) -> bool:
        """把内存设置原子写盘。返回 True 表示已落盘。"""
        with self.pacs_lock:
            payload = dict(self.pacs_data)
            payload.update(self.pacs_unknown)
            text = pacs_json_dump(payload, pms_indent=2)
        try:
            pacs_atomic_write_text(self.pacs_paths.prt_settings_file, text)
            return True
        except OSError as exc:
            pacs_logger.error("保存设置失败：%s", exc)
            return False

    # ------------------------------------------------------------------ 读
    def pacs_raw(self) -> dict[str, Any]:
        with self.pacs_lock:
            return dict(self.pacs_data)

    def pacs_unknown_keys(self) -> list[str]:
        with self.pacs_lock:
            return sorted(self.pacs_unknown.keys())

    def pacs_get_str(self, pms_key: str, pms_default: str = "") -> str:
        with self.pacs_lock:
            value = self.pacs_data.get(pms_key, pms_default)
        return "" if value is None else str(value)

    def pacs_get_bool(self, pms_key: str, pms_default: bool = False) -> bool:
        with self.pacs_lock:
            value = self.pacs_data.get(pms_key, pms_default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")

    def pacs_get_int(self, pms_key: str, pms_default: int = 0) -> int:
        with self.pacs_lock:
            value = self.pacs_data.get(pms_key, pms_default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return pms_default

    def pacs_get_many(self, pms_keys: list[str]) -> dict[str, Any]:
        with self.pacs_lock:
            return {key: self.pacs_data.get(key, PACS_SETTINGS_DEFAULTS.get(key)) for key in pms_keys}

    # ------------------------------------------------------------------ 写（立即落盘）
    def psm_set(self, pms_key: str, pms_value: Any, pms_save: bool = True) -> None:
        """写一个键并立即落盘。未知键也允许写（会进 unknown 区，便于排查拼写）。"""
        with self.pacs_lock:
            if pacs_is_known_key(pms_key):
                self.pacs_data[pms_key] = pacs_coerce(pms_key, pms_value)
            else:
                self.pacs_unknown[pms_key] = pms_value
                pacs_logger.warning("写入未登记的设置键「%s」——请把它加进 PACS_SETTINGS_DEFAULTS", pms_key)
        if pms_save:
            self.pacs_save()

    def psm_set_many(self, pms_values: dict[str, Any], pms_save: bool = True) -> None:
        with self.pacs_lock:
            for key, value in pms_values.items():
                if pacs_is_known_key(key):
                    self.pacs_data[key] = pacs_coerce(key, value)
                else:
                    self.pacs_unknown[key] = value
                    pacs_logger.warning("写入未登记的设置键「%s」", key)
        if pms_save:
            self.pacs_save()

    # ------------------------------------------------------------------ 便捷
    def pacs_app_header(self) -> str:
        return f"{PACS_APP_NAME} v{PACS_APP_VERSION}"
