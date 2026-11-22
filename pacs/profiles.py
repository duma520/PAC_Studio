# -*- coding: utf-8 -*-
"""分流方案的存取（多方案切换）。

真源是 `data/profiles.json`（方案清单 + 当前方案）+ `data/profiles/<文件>.json`（规则本体）。
规则文件与方案显示名分离，这样方案名可以随便用中文，不会把文件名搞脏。

保存策略：GUI 侧做 300~500ms 防抖（避免表格拖动/连续编辑时疯狂写盘），
但所有「切换方案 / 关闭窗口 / 应用 PAC」都会强制立即落盘。
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, Optional

from pacs.constants import (
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_APP_NAME,
    PACS_APP_VERSION,
    PACS_DEFAULT_PROXY_ADDRESS,
    PACS_DEFAULT_PROXY_SCHEME,
    PACS_LOGGER_NAME,
    PACS_PROFILE_NAME_MAX,
)
from pacs.paths import PacsRuntimePaths
from pacs.pac.builtin import pacs_new_document
from pacs.pac.model import PacsDocument
from pacs.settings import PacsSettingsManager
from pacs.utils import pacs_atomic_write_text, pacs_json_dump, pacs_json_load, pacs_now_text

pacs_logger = logging.getLogger(PACS_LOGGER_NAME + ".profiles")


class PacsProfileStore:
    """多方案管理器。所有写操作都会立刻写盘（除 GUI 防抖调用）。"""

    def __init__(self, pms_paths: PacsRuntimePaths, pms_settings: PacsSettingsManager) -> None:
        self.pacs_paths = pms_paths
        self.pacs_settings = pms_settings
        self.pacs_index_file = pms_paths.prt_profile_index_file
        self.pacs_index: dict[str, Any] = self._load_index()
        self.pacs_ensure_default()

    # ------------------------------------------------------------------ 索引
    def _load_index(self) -> dict[str, Any]:
        raw = pacs_json_load(self.pacs_index_file, pms_default={})
        if not isinstance(raw, dict):
            raw = {}
        entries = raw.get("profiles")
        clean: list[dict[str, str]] = []
        if isinstance(entries, list):
            for item in entries:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                file_name = str(item.get("file") or "").strip()
                if not name or not file_name:
                    continue
                clean.append({"name": name, "file": file_name})
        active = str(raw.get("active") or "").strip()
        if not active and clean:
            active = clean[0]["name"]
        return {"active": active, "profiles": clean}

    def _save_index(self) -> bool:
        try:
            pacs_atomic_write_text(
                self.pacs_index_file,
                pacs_json_dump(self.pacs_index, pms_indent=2),
            )
            return True
        except OSError as exc:
            pacs_logger.error("保存方案索引失败：%s", exc)
            return False

    # ------------------------------------------------------------------ 方案列表
    def pacs_profiles(self) -> list[dict[str, str]]:
        return [dict(item) for item in self.pacs_index.get("profiles", [])]

    def pacs_active_name(self) -> str:
        active = str(self.pacs_index.get("active") or "").strip()
        if active and self._find_entry(active):
            return active
        entries = self.pacs_profiles()
        if entries:
            self.pacs_index["active"] = entries[0]["name"]
            return entries[0]["name"]
        return ""

    def _find_entry(self, pms_name: str) -> Optional[dict[str, str]]:
        for item in self.pacs_index.get("profiles", []):
            if item.get("name") == pms_name:
                return item
        return None

    def _unique_file_name(self, pms_name: str) -> str:
        base = self.pacs_paths.prt_safe_profile_name(pms_name)
        candidate = f"{base}.json"
        used = {item.get("file") for item in self.pacs_index.get("profiles", [])}
        if candidate not in used:
            return candidate
        for index in range(2, 999):
            candidate = f"{base}-{index}.json"
            if candidate not in used:
                return candidate
        return f"{base}-{int(__import__('time').time())}.json"

    # ------------------------------------------------------------------ 默认方案
    def pacs_ensure_default(self) -> None:
        if self.pacs_profiles():
            return
        doc = pacs_new_document(
            "默认方案",
            self.pacs_settings.pacs_get_str("proxy.default_address", PACS_DEFAULT_PROXY_ADDRESS),
            self.pacs_settings.pacs_get_str("proxy.default_scheme", PACS_DEFAULT_PROXY_SCHEME),
        )
        self.pacs_create_profile("默认方案", doc, pms_set_active=True)

    # ------------------------------------------------------------------ 读写方案
    def pacs_profile_file(self, pms_name: str) -> Optional[Path]:
        entry = self._find_entry(pms_name)
        if entry is None:
            return None
        return self.pacs_paths.prt_profiles_dir / entry["file"]

    def pacs_load(self, pms_name: str = "") -> PacsDocument:
        name = pms_name or self.pacs_active_name()
        path = self.pacs_profile_file(name)
        if path is None or not path.is_file():
            doc = pacs_new_document(
                name or "默认方案",
                self.pacs_settings.pacs_get_str("proxy.default_address", PACS_DEFAULT_PROXY_ADDRESS),
                self.pacs_settings.pacs_get_str("proxy.default_scheme", PACS_DEFAULT_PROXY_SCHEME),
            )
            return doc
        raw = pacs_json_load(path, pms_default={})
        doc = PacsDocument.pacs_from_dict(raw if isinstance(raw, dict) else {}, name)
        doc.name = name
        return doc

    def pacs_save(self, pms_document: PacsDocument) -> bool:
        """保存方案本体（写规则文件 + 更新时间）。返回是否成功。"""
        name = pms_document.name or self.pacs_active_name()
        entry = self._find_entry(name)
        if entry is None:
            return self.pacs_create_profile(name, pms_document, pms_set_active=True)
        path = self.pacs_paths.prt_profiles_dir / entry["file"]
        doc = pms_document.pacs_clone()
        doc.name = name
        doc.updated_at = pacs_now_text()
        try:
            pacs_atomic_write_text(path, pacs_json_dump(doc.pacs_to_dict(), pms_indent=2))
            return True
        except OSError as exc:
            pacs_logger.error("保存方案失败：%s", exc)
            return False

    # ------------------------------------------------------------------ 增删改名
    def pacs_create_profile(
        self,
        pms_name: str,
        pms_document: Optional[PacsDocument] = None,
        pms_set_active: bool = True,
    ) -> bool:
        name = self.pacs_normalize_name(pms_name)
        if not name:
            return False
        if self._find_entry(name):
            name = self.pacs_normalize_name(f"{name} 2")
        file_name = self._unique_file_name(name)
        doc = (pms_document or pacs_new_document(name)).pacs_clone()
        doc.name = name
        doc.updated_at = pacs_now_text()
        try:
            pacs_atomic_write_text(
                self.pacs_paths.prt_profiles_dir / file_name,
                pacs_json_dump(doc.pacs_to_dict(), pms_indent=2),
            )
        except OSError as exc:
            pacs_logger.error("新建方案失败：%s", exc)
            return False
        self.pacs_index.setdefault("profiles", []).append({"name": name, "file": file_name})
        if pms_set_active:
            self.pacs_index["active"] = name
        return self._save_index()

    def pacs_rename_profile(self, pms_old: str, pms_new: str) -> bool:
        entry = self._find_entry(pms_old)
        if entry is None:
            return False
        name = self.pacs_normalize_name(pms_new)
        if not name or name == pms_old:
            return False
        if self._find_entry(name):
            return False
        entry["name"] = name
        # 文件名保持不变（避免移动文件带来的失败窗口），只改显示名
        doc = self.pacs_load(pms_old)
        doc.name = name
        self.pacs_save(doc)
        if self.pacs_index.get("active") == pms_old:
            self.pacs_index["active"] = name
        return self._save_index()

    def pacs_delete_profile(self, pms_name: str) -> bool:
        entries = self.pacs_index.get("profiles", [])
        if len(entries) <= 1:
            pacs_logger.warning("只剩一个方案，拒绝删除")
            return False
        entry = self._find_entry(pms_name)
        if entry is None:
            return False
        path = self.pacs_paths.prt_profiles_dir / entry["file"]
        try:
            if path.is_file():
                path.unlink()
        except OSError as exc:
            pacs_logger.error("删除方案文件失败：%s", exc)
            return False
        self.pacs_index["profiles"] = [item for item in entries if item.get("name") != pms_name]
        if self.pacs_index.get("active") == pms_name:
            self.pacs_index["active"] = self.pacs_index["profiles"][0]["name"]
        return self._save_index()

    def pacs_duplicate_profile(self, pms_name: str, pms_new_name: str) -> bool:
        doc = self.pacs_load(pms_name)
        doc.name = pms_new_name
        return self.pacs_create_profile(pms_new_name, doc, pms_set_active=True)

    def pacs_set_active(self, pms_name: str) -> bool:
        if self._find_entry(pms_name) is None:
            return False
        self.pacs_index["active"] = pms_name
        return self._save_index()

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def pacs_normalize_name(pms_name: str) -> str:
        text = str(pms_name or "").strip()
        text = "".join(ch for ch in text if ord(ch) >= 32)
        return text[:PACS_PROFILE_NAME_MAX]

    def pacs_export_bundle(self, pms_name: str = "") -> dict[str, Any]:
        """导出成一份自包含 JSON（便于分享/备份，不含任何账号密码）。"""
        doc = self.pacs_load(pms_name)
        return {
            "app": PACS_APP_NAME,
            "version": PACS_APP_VERSION,
            "exported_at": pacs_now_text(),
            "document": doc.pacs_to_dict(),
        }

    def pacs_import_bundle(self, pms_data: dict[str, Any], pms_name: str = "") -> bool:
        if not isinstance(pms_data, dict):
            return False
        raw = pms_data.get("document") if isinstance(pms_data.get("document"), dict) else pms_data
        doc = PacsDocument.pacs_from_dict(raw, pms_name or "导入的方案")
        doc.name = pms_name or doc.name or "导入的方案"
        return self.pacs_create_profile(doc.name, doc, pms_set_active=True)


def pacs_effective_scheme(pms_text: str) -> str:
    text = str(pms_text or "").upper()
    if text in (PACS_ACTION_PROXY, PACS_ACTION_SOCKS5, PACS_ACTION_MIXED):
        return text
    return PACS_ACTION_SOCKS5


def pacs_clone_document(pms_document: PacsDocument) -> PacsDocument:
    return copy.deepcopy(pms_document)
