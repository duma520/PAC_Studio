# -*- coding: utf-8 -*-
"""运行时路径解析（便携优先）。

规则（与 Proxy_Manager_Studio 同源思路）：
    1. 冻结（PyInstaller / Nuitka）时，主目录 = 可执行文件所在目录；
    2. 源码运行时，主目录 = 入口脚本 `PAC_Studio.py` 所在目录（往上找标记文件）；
    3. `--base` 参数可强制指定主目录（调试用）。
所有可写产物（data/ logs/ version/）都落在主目录下，便于整目录拷贝迁移。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

from pacs.constants import (
    PACS_DIR_DATA,
    PACS_DIR_DOCS,
    PACS_DIR_LOGS,
    PACS_DIR_PROFILES,
    PACS_DIR_SCAFFOLD,
    PACS_DIR_VERSION,
    PACS_ICON_FILENAME,
    PACS_ITERATION_DOC,
    PACS_MAIN_SCRIPT,
    PACS_PAC_FILENAME,
    PACS_SETTINGS_FILENAME,
    PACS_SETTINGS_BACKUP_FILENAME,
    PACS_PROFILE_INDEX_FILENAME,
    PACS_LOG_FILENAME,
)


class PacsRuntimePaths:
    """项目运行时目录与文件路径。

    每个访问器只拼路径，**不创建任何文件**；需要目录时调用 `prt_ensure_dirs()`。
    """

    def __init__(
        self,
        pms_base_override: Optional[Path] = None,
        pms_core_roots: Optional[Sequence[Path]] = None,
    ) -> None:
        self.pacs_base_override = Path(pms_base_override) if pms_base_override else None
        self.pacs_core_roots = [Path(p) for p in (pms_core_roots or [])]
        self.pacs_root = self.prt_detect_root()

    # ------------------------------------------------------------------ 主目录探测
    @staticmethod
    def prt_is_frozen() -> bool:
        return bool(getattr(sys, "frozen", False))

    @staticmethod
    def prt_root_markers() -> tuple[str, ...]:
        """判定「这是一个项目根目录」的标记文件。"""
        return (PACS_MAIN_SCRIPT, PACS_SETTINGS_FILENAME, ".gitignore")

    def prt_candidate_roots(self) -> list[Path]:
        roots: list[Path] = []
        if self.pacs_base_override is not None:
            roots.append(self.pacs_base_override)
        if self.prt_is_frozen():
            roots.append(Path(sys.executable).resolve().parent)
        else:
            try:
                entry = Path(sys.argv[0]).resolve()
                roots.append(entry.parent)
            except Exception:  # noqa: BLE001
                pass
            roots.append(Path(__file__).resolve().parent.parent)
        roots.extend(self.pacs_core_roots)
        return roots

    def prt_detect_root(self) -> Path:
        # --base 显式指定时直接采用（调试/测试用临时目录，不要求有标记文件）
        if self.pacs_base_override is not None:
            return self.pacs_base_override
        markers = self.prt_root_markers()
        for root in self.prt_candidate_roots():
            try:
                if any((root / marker).exists() for marker in markers):
                    return root
            except OSError:
                continue
        # 全部落空：退回本文件的上两级（源码运行的常规位置）
        return Path(__file__).resolve().parent.parent

    # ------------------------------------------------------------------ 目录
    def prt_dir(self, pms_name: str, pms_create: bool = True) -> Path:
        path = self.pacs_root / pms_name
        if pms_create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def prt_data_dir(self) -> Path:
        return self.prt_dir(PACS_DIR_DATA)

    @property
    def prt_logs_dir(self) -> Path:
        return self.prt_dir(PACS_DIR_LOGS)

    @property
    def prt_version_dir(self) -> Path:
        return self.prt_dir(PACS_DIR_VERSION)

    @property
    def prt_scaffold_dir(self) -> Path:
        return self.prt_dir(PACS_DIR_SCAFFOLD)

    @property
    def prt_docs_dir(self) -> Path:
        return self.prt_dir(PACS_DIR_DOCS)

    @property
    def prt_profiles_dir(self) -> Path:
        return self.prt_dir(PACS_DIR_DATA) / PACS_DIR_PROFILES

    # ------------------------------------------------------------------ 文件
    @property
    def prt_settings_file(self) -> Path:
        return self.prt_data_dir / PACS_SETTINGS_FILENAME

    @property
    def prt_settings_backup_file(self) -> Path:
        return self.prt_data_dir / PACS_SETTINGS_BACKUP_FILENAME

    @property
    def prt_pac_file(self) -> Path:
        """编译产物（当前生效的 PAC 文件），AutoConfigURL 指向它。"""
        return self.prt_data_dir / PACS_PAC_FILENAME

    @property
    def prt_profile_index_file(self) -> Path:
        return self.prt_data_dir / PACS_PROFILE_INDEX_FILENAME

    @property
    def prt_log_file(self) -> Path:
        return self.prt_logs_dir / PACS_LOG_FILENAME

    @property
    def prt_icon_file(self) -> Path:
        return self.pacs_root / PACS_ICON_FILENAME

    @property
    def prt_iteration_doc(self) -> Path:
        return self.pacs_root / PACS_ITERATION_DOC

    @property
    def prt_main_script(self) -> Path:
        return self.pacs_root / PACS_MAIN_SCRIPT

    def prt_profile_file(self, pms_name: str) -> Path:
        """某个分流方案的规则文件（data/profiles/<name>.json）。"""
        safe = self.prt_safe_profile_name(pms_name)
        return self.prt_profiles_dir / f"{safe}.json"

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def prt_safe_profile_name(pms_name: str) -> str:
        """把方案名收敛成安全文件名（去掉路径分隔符与 Windows 非法字符）。"""
        text = str(pms_name or "").strip() or "default"
        for bad in '<>:"/\\|?*':
            text = text.replace(bad, "_")
        text = "".join(ch for ch in text if ord(ch) >= 32).strip(" .")
        return text[:40] or "default"

    def prt_icon_exists(self) -> bool:
        """规则：icon.ico 存在才用，不存在就不引用（绝不因缺文件崩溃）。"""
        try:
            return self.prt_icon_file.is_file()
        except OSError:
            return False

    def prt_ensure_dirs(self) -> None:
        for path in (
            self.prt_data_dir,
            self.prt_logs_dir,
            self.prt_version_dir,
            self.prt_profiles_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
