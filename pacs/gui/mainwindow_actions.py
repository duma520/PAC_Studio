# -*- coding: utf-8 -*-
"""主窗口 · 动作（mixin）：编译、导入导出、应用到 Windows、还原、设置、关于。

所有耗时步骤都把函数体交给 `self.pacs_start_worker(...)`，主线程只处理结果与提示。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PySide6.QtWidgets import QFileDialog

from pacs.constants import (
    PACS_APP_NAME,
    PACS_APP_VERSION,
    PACS_COMPILE_OPTIMIZED,
)
from pacs.gui.dialogs.omega_dialog import PacsOmegaImportDialog
from pacs.gui.dialogs.settings_dialog import PacsSettingsDialog
from pacs.gui.widgets import pacs_confirm, pacs_error, pacs_info, pacs_warn
from pacs.pac.compiler import PacsCompileResult, pacs_compile
from pacs.pac.model import PacsDocument
from pacs.pac.omega_export import PacsOmegaExportResult, pacs_export_omega
from pacs.pac.omega_import import PacsOmegaImportResult, pacs_import_omega
from pacs.pac.parser import pacs_parse_pac
from pacs.sysproxy import PacsWindowsSystemProxy
from pacs.utils import pacs_atomic_write_text, pacs_json_dump, pacs_open_in_explorer, pacs_read_text


class PacsActionsMixin:
    """依赖宿主窗口：pacs_document / pacs_settings / pacs_paths / pacs_sysproxy 等。"""

    # ================================================================== 编译 / 预览
    def pacs_compile_sync(self) -> Optional[PacsCompileResult]:
        mode = self.pacs_settings.pacs_get_str("pac.compile_mode", PACS_COMPILE_OPTIMIZED)
        result = pacs_compile(
            self.pacs_document,
            mode,
            self.pacs_settings.pacs_get_bool("pac.escape_unicode", True),
        )
        self.pacs_compile_result = result
        return result

    def pacs_refresh_preview_async(self) -> None:
        if self.pacs_worker is not None and self.pacs_worker.isRunning():
            return
        doc = self.pacs_document.pacs_clone()
        mode = self.pacs_settings.pacs_get_str("pac.compile_mode", PACS_COMPILE_OPTIMIZED)
        escape = self.pacs_settings.pacs_get_bool("pac.escape_unicode", True)
        self.pacs_progress.pacs_start("编译预览")
        self.pacs_worker = self.pacs_start_worker(
            lambda progress: pacs_compile(doc, mode, escape, progress),
            self.pacs_on_preview_done,
        )

    def pacs_compile_preview(self) -> None:
        self.pacs_tabs.setCurrentWidget(self.pacs_tabs.widget(1))
        self.pacs_refresh_preview_async()

    def pacs_on_preview_done(self, pms_result: PacsCompileResult) -> None:
        self.pacs_compile_result = pms_result
        self.pacs_script_edit.setPlainText(pms_result.text)
        self.pacs_progress.pacs_finish("编译完成")
        self.pacs_progress.pacs_hide_after()
        if pms_result.warnings:
            self.pacs_show_toast(f"编译完成，但有 {len(pms_result.warnings)} 条提示（见脚本头部注释）")
        else:
            self.pacs_show_toast(f"编译完成：{pms_result.pacs_summary()}")

    def pacs_toggle_script_editable(self) -> None:
        editable = not self.pacs_script_edit.isReadOnly()
        self.pacs_script_edit.setReadOnly(editable)
        if not editable:
            self.pacs_show_toast("已切到可编辑：改完点「解析回规则表」或「另存为 .pac」")
        else:
            self.pacs_show_toast("已切回只读预览")

    def pacs_parse_script_back(self) -> None:
        text = self.pacs_script_edit.toPlainText()
        if not text.strip():
            pacs_info(self, "提示", "脚本是空的，没什么可解析。")
            return
        parsed = pacs_parse_pac(text)
        if not parsed.recognized:
            pacs_warn(
                self,
                "解析不了这份脚本",
                "这份脚本不是本程序生成的格式，规则表<b>保持不变</b>。\n"
                "可以继续手写脚本并用「另存为 .pac」保存；结构化编辑请回到规则表。",
            )
            return
        if not pacs_confirm(
            self,
            "解析回规则表",
            f"识别到 {len(parsed.rules)} 条规则、默认动作「{parsed.default_action}」。\n"
            "继续会用它<b>替换</b>当前方案的规则表，确定吗？",
        ):
            return
        doc = parsed.pacs_apply_to(self.pacs_document)
        doc.name = self.pacs_document.name
        self.pacs_document = doc
        self.pacs_model.pacs_set_document(doc)
        self.pacs_refresh_default_row()
        self.pacs_refresh_status()
        self.pacs_save_now("解析回规则表")
        self.pacs_refresh_preview_async()
        self.pacs_show_toast(f"已从脚本回填 {len(parsed.rules)} 条规则")

    def pacs_save_pac_as(self) -> None:
        text = self.pacs_script_edit.toPlainText()
        if not text.strip():
            pacs_info(self, "提示", "先编译预览或手写脚本，再另存。")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "保存 PAC 文件",
            str(self.pacs_paths.prt_data_dir / "pac_export.pac"),
            "PAC 脚本 (*.pac);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            pacs_atomic_write_text(Path(path), text)
        except OSError as exc:
            pacs_error(self, "保存失败", f"写文件失败：{exc}")
            return
        self.pacs_show_toast(f"已保存：{path}")

    def pacs_open_data_dir(self) -> None:
        pacs_open_in_explorer(self.pacs_paths.prt_data_dir)

    # ================================================================== 导入
    def pacs_import_omega(self) -> None:
        start_dir = self.pacs_settings.pacs_get_str("omega.last_import_path", "") or str(Path.home())
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择 ZeroOmega 导出的 PAC 文件", start_dir, "PAC 脚本 (*.pac);;所有文件 (*.*)"
        )
        if not path:
            return
        self.pacs_settings.psm_set("omega.last_import_path", path)
        text = pacs_read_text(Path(path))
        if not text.strip():
            pacs_error(self, "读取失败", f"文件读不出内容：{path}")
            return
        self.pacs_progress.pacs_start("导入 ZeroOmega")
        self.pacs_worker = self.pacs_start_worker(
            lambda progress: pacs_import_omega(text, self.pacs_document.default_proxy, progress),
            lambda result: self.pacs_on_import_done(result, path),
        )

    def pacs_on_import_done(self, pms_result: PacsOmegaImportResult, pms_path: str) -> None:
        self.pacs_progress.pacs_finish("导入解析完成")
        self.pacs_progress.pacs_hide_after()
        if not pms_result.document.rules:
            pacs_warn(
                self,
                "没导入到规则",
                "这份文件里没有识别到可用规则。\n" + "\n".join(pms_result.warnings[:5]),
            )
            return
        dialog = PacsOmegaImportDialog(pms_result, Path(pms_path).name, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        imported = pms_result.document
        if dialog.pacs_mode == PacsOmegaImportDialog.MODE_NEW:
            if not self.pacs_store.pacs_create_profile(dialog.pacs_new_name, imported, pms_set_active=True):
                pacs_error(self, "新建方案失败", "方案名可能重复，或文件不可写。")
                return
            self.pacs_reload_all()
        else:
            if dialog.pacs_mode == PacsOmegaImportDialog.MODE_REPLACE:
                self.pacs_document.rules = [rule.pacs_clone() for rule in imported.rules]
            else:
                self.pacs_document.rules.extend(rule.pacs_clone() for rule in imported.rules)
            self.pacs_document.default_action = imported.default_action
            if imported.default_proxy:
                self.pacs_document.default_proxy = imported.default_proxy
            self.pacs_document.default_scheme = imported.default_scheme
            self.pacs_model.pacs_set_document(self.pacs_document)
            self.pacs_refresh_default_row()
            self.pacs_refresh_status()
            self.pacs_save_now("导入 ZeroOmega")
        self.pacs_refresh_preview_async()
        self.pacs_show_toast(f"已导入 {len(imported.rules)} 条规则")

    # ================================================================== 导出
    def pacs_export_omega(self) -> None:
        if not self.pacs_document.rules:
            pacs_info(self, "提示", "当前方案还没有规则，先导入或添加规则。")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出为 ZeroOmega PAC",
            str(self.pacs_paths.prt_data_dir / "zeroomega_export.pac"),
            "PAC 脚本 (*.pac);;所有文件 (*.*)",
        )
        if not path:
            return
        doc = self.pacs_document.pacs_clone()
        style = self.pacs_settings.pacs_get_str("omega.export_style", "compatible")
        escape = self.pacs_settings.pacs_get_bool("omega.escape_unicode", True)
        self.pacs_progress.pacs_start("导出 ZeroOmega")
        self.pacs_worker = self.pacs_start_worker(
            lambda progress: pacs_export_omega(doc, style, escape, progress),
            lambda result: self.pacs_on_export_done(result, path),
        )

    def pacs_on_export_done(self, pms_result: PacsOmegaExportResult, pms_path: str) -> None:
        self.pacs_progress.pacs_finish("导出完成")
        self.pacs_progress.pacs_hide_after()
        try:
            pacs_atomic_write_text(Path(pms_path), pms_result.text)
        except OSError as exc:
            pacs_error(self, "保存失败", f"写文件失败：{exc}")
            return
        pacs_info(
            self,
            "导出完成",
            f"已保存到：\n{pms_path}\n\n"
            f"规则 {pms_result.rule_count} 条 · {pms_result.size_bytes / 1024:.1f} KB\n"
            "复制这个文件的内容，粘贴到 ZeroOmega 的「自动切换模式 → PAC 脚本」即可。",
        )

    def pacs_export_bundle(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "导出方案为 JSON",
            str(self.pacs_paths.prt_data_dir / f"{self.pacs_document.name}.json"),
            "JSON (*.json);;所有文件 (*.*)",
        )
        if not path:
            return
        bundle = self.pacs_store.pacs_export_bundle(self.pacs_document.name)
        try:
            pacs_atomic_write_text(Path(path), pacs_json_dump(bundle, pms_indent=2))
        except OSError as exc:
            pacs_error(self, "导出失败", f"写文件失败：{exc}")
            return
        self.pacs_show_toast(f"方案已导出：{path}")

    # ================================================================== 应用到 Windows
    def pacs_apply_to_windows(self) -> None:
        problems = self.pacs_document.pacs_validate_all()
        if problems:
            head = "\n".join(f"第 {index} 条：{reason}" for index, reason in problems[:8])
            more = f"\n……共 {len(problems)} 处" if len(problems) > 8 else ""
            if not pacs_confirm(
                self,
                "规则体检发现问题",
                f"{head}{more}\n\n有问题的规则会被跳过或按兜底处理。仍要继续应用吗？",
            ):
                return
        if not self.pacs_save_now("应用前保存"):
            return
        doc = self.pacs_document.pacs_clone()
        mode = self.pacs_settings.pacs_get_str("pac.compile_mode", PACS_COMPILE_OPTIMIZED)
        escape = self.pacs_settings.pacs_get_bool("pac.escape_unicode", True)
        pac_file = self.pacs_paths.prt_pac_file
        self.pacs_progress.pacs_start("应用 PAC 到 Windows")
        self.pacs_worker = self.pacs_start_worker(
            lambda progress: self.pacs_apply_task(doc, mode, escape, pac_file, progress),
            self.pacs_on_apply_done,
        )

    def pacs_apply_task(
        self,
        pms_document: PacsDocument,
        pms_mode: str,
        pms_escape: bool,
        pms_pac_file: Path,
        pms_progress,
    ) -> dict[str, Any]:
        if callable(pms_progress):
            pms_progress(5, "编译 PAC")
        compiled = pacs_compile(pms_document, pms_mode, pms_escape)
        if callable(pms_progress):
            pms_progress(45, "写入 PAC 文件")
        pacs_atomic_write_text(pms_pac_file, compiled.text)
        if callable(pms_progress):
            pms_progress(65, "备份原系统代理")
        if not self.pacs_settings.pacs_get_bool("system_proxy.backup_saved", False):
            self.pacs_sysproxy.pacs_backup_to_settings(
                self.pacs_settings, self.pacs_paths.prt_data_dir / "system_proxy_backup.json"
            )
        if callable(pms_progress):
            pms_progress(80, "写入 Windows 代理设置")
        ok = self.pacs_sysproxy.pacs_enable_pac_file(pms_pac_file)
        if callable(pms_progress):
            pms_progress(100, "完成")
        return {
            "ok": ok,
            "compiled": compiled,
            "pac_file": str(pms_pac_file),
            "url": PacsWindowsSystemProxy.pacs_file_url(pms_pac_file),
        }

    def pacs_on_apply_done(self, pms_payload: dict[str, Any]) -> None:
        self.pacs_progress.pacs_finish("应用完成")
        self.pacs_progress.pacs_hide_after()
        compiled: PacsCompileResult = pms_payload["compiled"]
        if pms_payload.get("ok"):
            self.pacs_settings.psm_set("system_proxy.enabled", True)
            self.pacs_refresh_status()
            pacs_info(
                self,
                "已应用到 Windows",
                f"Windows 现在会走 PAC：\n{pms_payload['url']}\n\n"
                f"{compiled.pacs_summary()}\n\n"
                "提示：部分浏览器需要重启或等几秒才读取新设置；如果某个老程序不认，"
                "可在「设置」里把默认协议改成 HTTP 代理。",
            )
        else:
            pacs_error(
                self,
                "应用失败",
                "写注册表失败（可能被安全软件拦截或没有权限）。\n"
                f"PAC 文件本身已生成：{pms_payload['pac_file']}",
            )

    # ================================================================== 还原
    def pacs_restore_windows(self) -> None:
        force_disable = False
        if not self.pacs_settings.pacs_get_bool("system_proxy.backup_saved", False):
            if not pacs_confirm(
                self,
                "没有备份",
                "还没有备份过你原来的系统代理设置，无法还原。\n\n"
                "要直接关闭系统代理（清空 AutoConfigURL、ProxyEnable=0）吗？",
            ):
                return
            force_disable = True
        self.pacs_progress.pacs_start("还原系统代理" if not force_disable else "关闭系统代理")
        self.pacs_worker = self.pacs_start_worker(
            lambda progress: self.pacs_restore_task(progress, force_disable),
            self.pacs_on_restore_done,
        )

    def pacs_restore_task(self, pms_progress, pms_force_disable: bool) -> dict[str, Any]:
        if callable(pms_progress):
            pms_progress(30, "写入注册表")
        if pms_force_disable:
            ok = self.pacs_sysproxy.pacs_disable()
        else:
            ok = self.pacs_sysproxy.pacs_restore_from_settings(
                self.pacs_settings, self.pacs_paths.prt_data_dir / "system_proxy_backup.json"
            )
        if callable(pms_progress):
            pms_progress(100, "完成")
        return {"ok": ok, "state": self.pacs_sysproxy.pacs_read_current()}

    def pacs_on_restore_done(self, pms_payload: dict[str, Any]) -> None:
        self.pacs_progress.pacs_finish("还原完成")
        self.pacs_progress.pacs_hide_after()
        self.pacs_settings.psm_set("system_proxy.enabled", False)
        self.pacs_refresh_status()
        state = pms_payload.get("state") or {}
        if pms_payload.get("ok"):
            pacs_info(
                self,
                "已还原",
                "当前系统代理状态：\n"
                f"ProxyEnable = {state.get('enable')}\n"
                f"ProxyServer = {state.get('server') or '（空）'}\n"
                f"AutoConfigURL = {state.get('auto_config_url') or '（无）'}",
            )
        else:
            pacs_warn(self, "还原未完成", "没有可用的备份，或写注册表失败。可手动到 Windows 设置里改。")

    # ================================================================== 设置 / 关于
    def pacs_open_settings(self) -> None:
        dialog = PacsSettingsDialog(self.pacs_paths, self.pacs_settings, self.pacs_autostart, self)
        dialog.exec()
        self.pacs_rebuild_tray()
        self.pacs_refresh_preview_async()

    def pacs_show_about(self) -> None:
        pacs_info(
            self,
            "说明 / 关于",
            f"<b>{PACS_APP_NAME} v{PACS_APP_VERSION}</b><br><br>"
            "用途：编辑 PAC 分流规则、一键让 Windows 走 PAC、与 ZeroOmega 的 PAC 互转。<br><br>"
            f"PAC 文件：{self.pacs_paths.prt_pac_file}<br>"
            f"数据目录：{self.pacs_paths.prt_data_dir}<br><br>"
            "规则：<br>"
            "· 规则从上往下判断，先命中先生效；<br>"
            "· localhost / 127.0.0.1 / ::1 / 纯主机名一律直连；<br>"
            "· 默认外部代理 <b>***已脱敏***-内网IP:20808</b>（可在设置里改）；<br>"
            "· 退出时默认还原你原来的系统代理设置（可在设置里关掉）。",
        )
