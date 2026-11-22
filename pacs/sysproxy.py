# -*- coding: utf-8 -*-
"""Windows 系统代理（PAC / 自动配置脚本）控制。

语义与 Proxy_Manager_Studio 的 `PmsWindowsSystemProxy` 保持一致（同一套注册表口径），
新增两点：
    1. 备份除了写设置文件，还额外落一份 `data/system_proxy_backup.json`（设置文件损坏时的退路）；
    2. 提供 `pacs_current_pac_file()`，用来判断「当前 Windows 用的 PAC 是不是本项目的」。

**为什么开启 PAC 必须把 ProxyEnable 置 0**：
`AutoConfigURL`（自动配置脚本）与 `ProxyEnable/ProxyServer`（固定代理）是同一组
「每连接代理配置」的两个来源。两者的语义互斥；同时留下的结果是部分程序读 PAC、
部分程序读固定代理，表现为「一个网站走了代理、另一个没走」的说不清行为。
所以开 PAC 时显式清零 ProxyEnable，关 PAC 时按备份还原。

**还原纪律**：备份必须连 `AutoConfigURL` 一起存。用户原本可能正在用公司/校园网的 PAC，
只还原另外三个键等于把那个 PAC 永久删掉。原值为空串时**删除该注册表值**，
而不是写空串——两者在 WinINET 里不等价（写空串等于「配了一个空脚本」）。
"""

from __future__ import annotations

import ctypes
import logging
from pathlib import Path
from typing import Any, Optional

from pacs.constants import PACS_DEFAULT_PROXY_ADDRESS, PACS_IS_WINDOWS, PACS_LOGGER_NAME
from pacs.settings import PacsSettingsManager
from pacs.utils import pacs_atomic_write_text, pacs_json_dump, pacs_json_load

pacs_logger = logging.getLogger(PACS_LOGGER_NAME + ".sysproxy")


class PacsWindowsSystemProxy:
    """HKCU Internet Settings 读写 + 备份还原。非 Windows 上所有操作安全返回 False。"""

    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
    VALUE_ENABLE = "ProxyEnable"
    VALUE_SERVER = "ProxyServer"
    VALUE_BYPASS = "ProxyOverride"
    VALUE_AUTO_CONFIG_URL = "AutoConfigURL"

    def __init__(self, pms_logger: Optional[logging.Logger] = None) -> None:
        self.pacs_logger = pms_logger or pacs_logger

    # ------------------------------------------------------------------ 读
    def pacs_read_current(self) -> dict[str, Any]:
        state: dict[str, Any] = {"enable": 0, "server": "", "bypass": "", "auto_config_url": ""}
        if not PACS_IS_WINDOWS:
            return state
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as key:
                for value_name, field in (
                    (self.VALUE_ENABLE, "enable"),
                    (self.VALUE_SERVER, "server"),
                    (self.VALUE_BYPASS, "bypass"),
                    (self.VALUE_AUTO_CONFIG_URL, "auto_config_url"),
                ):
                    try:
                        value, _kind = winreg.QueryValueEx(key, value_name)
                        state[field] = value
                    except FileNotFoundError:
                        continue
        except OSError as exc:
            self.pacs_logger.warning("读取系统代理失败：%s", exc)
        return state

    def pacs_is_pac_enabled(self) -> bool:
        state = self.pacs_read_current()
        return bool(str(state.get("auto_config_url") or "").strip())

    def pacs_current_pac_file(self) -> str:
        """当前 AutoConfigURL 指向的本地文件路径（file:/// 转回路径）；无则空串。"""
        url = str(self.pacs_read_current().get("auto_config_url") or "").strip()
        if not url:
            return ""
        if url.lower().startswith("file:///"):
            text = url[8:]
            try:
                from urllib.parse import unquote

                return unquote(text).replace("/", "\\")
            except Exception:  # noqa: BLE001
                return text
        return url

    # ------------------------------------------------------------------ 写
    def pacs_write_registry(
        self,
        pms_enable: int,
        pms_server: str,
        pms_bypass: str,
        pms_auto_config_url: Optional[str] = None,
    ) -> bool:
        """写 4 个键。`auto_config_url` 为空 → 删除该值（不是写空串）。"""
        if not PACS_IS_WINDOWS:
            self.pacs_logger.warning("非 Windows 环境，跳过写注册表")
            return False
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, self.VALUE_ENABLE, 0, winreg.REG_DWORD, int(pms_enable))
                if pms_server:
                    winreg.SetValueEx(key, self.VALUE_SERVER, 0, winreg.REG_SZ, str(pms_server))
                winreg.SetValueEx(key, self.VALUE_BYPASS, 0, winreg.REG_SZ, str(pms_bypass))
                self._write_auto_config_url(key, winreg, pms_auto_config_url)
            return True
        except OSError as exc:
            self.pacs_logger.error("写入系统代理失败：%s", exc)
            return False

    def _write_auto_config_url(self, pms_key: Any, pms_winreg: Any, pms_url: Optional[str]) -> None:
        text = str(pms_url or "").strip()
        if text:
            pms_winreg.SetValueEx(pms_key, self.VALUE_AUTO_CONFIG_URL, 0, pms_winreg.REG_SZ, text)
            return
        try:
            pms_winreg.DeleteValue(pms_key, self.VALUE_AUTO_CONFIG_URL)
        except FileNotFoundError:
            pass

    def pacs_refresh(self) -> None:
        """通知系统立即刷新代理设置（否则要重启浏览器才生效）。"""
        if not PACS_IS_WINDOWS:
            return
        try:
            internet_set_option = ctypes.windll.wininet.InternetSetOptionW
            internet_set_option(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
            internet_set_option(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
        except Exception as exc:  # noqa: BLE001
            self.pacs_logger.debug("刷新系统代理设置失败：%s", exc)

    # ------------------------------------------------------------------ 业务
    @staticmethod
    def pacs_file_url(pms_path: Path) -> str:
        return Path(pms_path).resolve().as_uri()

    def pacs_enable_pac_file(self, pms_pac_file: Path) -> bool:
        """让 Windows 走指定的（已存在的）PAC 文件。**不改文件内容**。"""
        path = Path(pms_pac_file)
        if not path.is_file():
            self.pacs_logger.warning("启用 PAC 失败：文件不存在 %s", path)
            return False
        url = self.pacs_file_url(path)
        state = self.pacs_read_current()
        ok = self.pacs_write_registry(
            0, str(state.get("server") or ""), str(state.get("bypass") or ""), url
        )
        if ok:
            self.pacs_refresh()
            self.pacs_logger.info("系统代理已切到 PAC：%s（ProxyEnable=0）", url)
        return ok

    def pacs_disable(self, pms_bypass: str = "") -> bool:
        """关闭系统代理：ProxyEnable=0 且删除 AutoConfigURL。"""
        state = self.pacs_read_current()
        ok = self.pacs_write_registry(
            0,
            str(state.get("server") or ""),
            pms_bypass or str(state.get("bypass") or ""),
            "",
        )
        if ok:
            self.pacs_refresh()
            self.pacs_logger.info("系统代理已关闭")
        return ok

    # ------------------------------------------------------------------ 备份 / 还原
    def pacs_backup_to_settings(
        self,
        pms_settings: PacsSettingsManager,
        pms_backup_file: Optional[Path] = None,
    ) -> dict[str, Any]:
        state = self.pacs_read_current()
        pms_settings.psm_set_many(
            {
                "system_proxy.backup_saved": True,
                "system_proxy.original_enable": int(state.get("enable") or 0),
                "system_proxy.original_server": str(state.get("server") or ""),
                "system_proxy.original_bypass": str(state.get("bypass") or ""),
                "system_proxy.original_auto_config_url": str(state.get("auto_config_url") or ""),
            }
        )
        if pms_backup_file is not None:
            try:
                pacs_atomic_write_text(
                    Path(pms_backup_file),
                    pacs_json_dump({"saved_at": _now_text(), **state}, pms_indent=2),
                )
            except OSError as exc:
                self.pacs_logger.warning("写系统代理备份文件失败：%s", exc)
        self.pacs_logger.info(
            "已备份原系统代理：enable=%s server=%s auto_config_url=%s",
            state.get("enable"),
            state.get("server"),
            state.get("auto_config_url") or "（无）",
        )
        return state

    def pacs_restore_from_settings(
        self,
        pms_settings: PacsSettingsManager,
        pms_backup_file: Optional[Path] = None,
    ) -> bool:
        """按备份还原。设置里没备份时，尝试读独立备份文件。"""
        if not pms_settings.pacs_get_bool("system_proxy.backup_saved", False):
            if pms_backup_file is not None:
                data = pacs_json_load(Path(pms_backup_file), pms_default=None)
                if isinstance(data, dict):
                    pms_settings.psm_set_many(
                        {
                            "system_proxy.backup_saved": True,
                            "system_proxy.original_enable": int(data.get("enable") or 0),
                            "system_proxy.original_server": str(data.get("server") or ""),
                            "system_proxy.original_bypass": str(data.get("bypass") or ""),
                            "system_proxy.original_auto_config_url": str(data.get("auto_config_url") or ""),
                        }
                    )
                    self.pacs_logger.info("已从独立备份文件恢复系统代理备份")
        if not pms_settings.pacs_get_bool("system_proxy.backup_saved", False):
            return False
        enable = pms_settings.pacs_get_int("system_proxy.original_enable", 0)
        server = pms_settings.pacs_get_str("system_proxy.original_server", "")
        bypass = pms_settings.pacs_get_str("system_proxy.original_bypass", "")
        auto_config_url = pms_settings.pacs_get_str("system_proxy.original_auto_config_url", "")
        ok = self.pacs_write_registry(1 if enable else 0, server, bypass, auto_config_url)
        if ok:
            self.pacs_refresh()
            pms_settings.psm_set("system_proxy.enabled", False)
            self.pacs_logger.info(
                "系统代理已还原：enable=%s server=%s auto_config_url=%s",
                enable,
                server,
                auto_config_url or "（无）",
            )
        return ok

    # ------------------------------------------------------------------ 状态描述
    def pacs_describe(self, pms_own_pac_file: Optional[Path] = None) -> str:
        state = self.pacs_read_current()
        url = str(state.get("auto_config_url") or "").strip()
        if not url:
            if int(state.get("enable") or 0):
                return f"固定代理：{state.get('server') or '（未填）'}"
            return "未使用系统代理"
        own = ""
        if pms_own_pac_file is not None:
            try:
                own = self.pacs_file_url(Path(pms_own_pac_file))
            except Exception:  # noqa: BLE001
                own = ""
        if own and url == own:
            return "PAC 已生效（本程序的 PAC）"
        return f"PAC 已生效（其它脚本）：{url}"


def _now_text() -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M:%S")


#: 便于其它模块直接拿默认代理地址做提示
DEFAULT_PROXY_HINT = PACS_DEFAULT_PROXY_ADDRESS
