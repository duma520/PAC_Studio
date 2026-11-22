# -*- coding: utf-8 -*-
"""界面主题：字体选择 + 系统默认风格。

风格纪律：**不覆写样式表**，控件外观、配色、圆角、行高全部交给 Windows 系统主题，
这样界面在深浅色主题、不同 DPI、不同 Windows 版本下都和系统原生程序一致。

字体纪律（项目规则）：优先免费可商用字体——阿里巴巴普惠体 / 思源黑体 / HarmonyOS Sans；
**禁用**微软雅黑、苹方、方正系、汉仪系等需要授权的字体。系统里一个候选都没有时
不强行指定家族（交回系统默认），避免出现方块或空白。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from pacs.constants import PACS_APP_NAME, PACS_APP_VERSION

#: 按优先级排列的免费可商用字体（中英文名都试）
PACS_FONT_CANDIDATES: tuple[str, ...] = (
    "阿里巴巴普惠体 3.0",
    "Alibaba PuHuiTi 3.0",
    "阿里巴巴普惠体",
    "Alibaba PuHuiTi",
    "思源黑体 CN",
    "思源黑体",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "HarmonyOS Sans SC",
    "HarmonyOS Sans",
)

#: 明确禁用的商用授权字体（命中说明候选列表写错了，直接忽略）
PACS_FORBIDDEN_FONTS: tuple[str, ...] = (
    "微软雅黑",
    "microsoft yahei",
    "苹方",
    "pingfang",
    "方正",
    "fz",
    "汉仪",
    "hy",
)


def pacs_is_forbidden_font(pms_family: str) -> bool:
    text = str(pms_family or "").strip().lower()
    if not text:
        return False
    return any(bad in text for bad in PACS_FORBIDDEN_FONTS)


def pacs_available_families() -> set[str]:
    try:
        return set(QFontDatabase.families())
    except Exception:  # noqa: BLE001 无 GUI 环境时返回空集
        return set()


def pacs_choose_font_family(pms_available: Optional[set[str]] = None) -> str:
    """选第一个可用的免费可商用字体；一个都没有则返回空串（不强行指定）。"""
    families = pms_available if pms_available is not None else pacs_available_families()
    if not families:
        return ""
    lowered = {family.lower(): family for family in families}
    for candidate in PACS_FONT_CANDIDATES:
        if pacs_is_forbidden_font(candidate):
            continue
        actual = lowered.get(candidate.lower())
        if actual and not pacs_is_forbidden_font(actual):
            return actual
    return ""


def pacs_apply_app_font(pms_app: QApplication, pms_point_size: int = 10) -> str:
    """只应用字体，**不碰样式表**——界面风格保持系统默认。

    返回实际使用的字体名（空串 = 交回系统默认字体）。
    """
    family = pacs_choose_font_family()
    if family:
        pms_app.setFont(QFont(family, pms_point_size))
    return family


def pacs_window_title(pms_suffix: str = "") -> str:
    base = f"{PACS_APP_NAME} v{PACS_APP_VERSION}"
    return f"{base} · {pms_suffix}" if pms_suffix else base
