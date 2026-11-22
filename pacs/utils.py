# -*- coding: utf-8 -*-
"""通用工具：原子写、JS 字符串转义 / 反转义、JSON 读写、CIDR 掩码换算。"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Sequence

from pacs.constants import PACS_APP_NAME, PACS_LOGGER_NAME

pacs_logger = logging.getLogger(PACS_LOGGER_NAME + ".utils")


# --------------------------------------------------------------------------------------
# 原子写
# --------------------------------------------------------------------------------------
def pacs_atomic_write_text(pms_path: Path, pms_text: str, pms_encoding: str = "utf-8") -> bool:
    """原子写文本：同目录临时文件 + os.replace，避免半截文件。

    返回 True 表示已落盘；任何 OSError 直接抛出，由调用方决定怎么提示。
    """
    path = Path(pms_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", suffix=".part", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=pms_encoding, newline="\n") as handle:
            handle.write(pms_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        return True
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def pacs_read_text(pms_path: Path, pms_encoding: str = "utf-8") -> str:
    """读文本；文件不存在或解码失败都返回空串（调用方不必再 try）。"""
    try:
        return Path(pms_path).read_text(encoding=pms_encoding)
    except (OSError, UnicodeDecodeError) as exc:
        pacs_logger.debug("读取文本失败：%s（%s）", pms_path, exc)
        return ""


# --------------------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------------------
def pacs_json_dump(pms_data: Any, pms_indent: int = 2, pms_ensure_ascii: bool = False) -> str:
    return json.dumps(pms_data, ensure_ascii=pms_ensure_ascii, indent=pms_indent, sort_keys=False)


def pacs_json_load(pms_path: Path, pms_default: Any = None) -> Any:
    """读 JSON；损坏时把原文件改名成 .bad-<时间戳> 并返回默认值（绝不静默丢数据）。"""
    path = Path(pms_path)
    if not path.is_file():
        return pms_default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        bad = path.with_suffix(path.suffix + f".bad-{stamp}")
        try:
            path.replace(bad)
            pacs_logger.warning("配置文件损坏，已改名为 %s（原因：%s）", bad.name, exc)
        except OSError:
            pacs_logger.warning("配置文件损坏且无法改名：%s", exc)
        return pms_default


# --------------------------------------------------------------------------------------
# JS 字符串
# --------------------------------------------------------------------------------------
_JS_UNICODE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
_JS_ESCAPE_MAP = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def pacs_js_unescape(pms_text: str) -> str:
    """把 JS 字符串字面量里的 \\uXXXX / \\" / \\\\ 还原成真实字符（ZeroOmega 导出常带 \\u 转义）。"""
    if not pms_text:
        return ""
    text = _JS_UNICODE_RE.sub(lambda m: chr(int(m.group(1), 16)), pms_text)
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            mapping = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def pacs_js_escape(pms_text: str, pms_escape_unicode: bool = False) -> str:
    """把普通字符串变成可直接塞进 JS 双引号字面量的内容。

    pms_escape_unicode=True 时把非 ASCII 也转成 \\uXXXX（与 ZeroOmega 导出风格一致）。
    """
    text = str(pms_text or "")
    out: list[str] = []
    for ch in text:
        if ch in _JS_ESCAPE_MAP:
            out.append(_JS_ESCAPE_MAP[ch])
        elif ord(ch) < 32:
            out.append("\\u%04x" % ord(ch))
        elif pms_escape_unicode and ord(ch) > 126:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def pacs_js_string_literal(pms_text: str, pms_escape_unicode: bool = False) -> str:
    return '"' + pacs_js_escape(pms_text, pms_escape_unicode) + '"'


# --------------------------------------------------------------------------------------
# 文本 / 转换
# --------------------------------------------------------------------------------------
def pacs_safe_int(pms_value: Any, pms_default: int = 0) -> int:
    try:
        return int(pms_value)
    except (TypeError, ValueError):
        return pms_default


def pacs_multiline_to_list(pms_text: str) -> list[str]:
    """多行文本 → 去空行去首尾空白的小写行列表。"""
    items: list[str] = []
    for line in str(pms_text or "").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or text.startswith("//"):
            continue
        items.append(text.lower())
    return items


def pacs_split_proxy(pms_address: str) -> tuple[str, int]:
    """把 `1.2.3.4:8080` / `[::1]:8080` 拆成 (host, port)；解析失败端口返回 0。"""
    text = str(pms_address or "").strip()
    if not text:
        return "", 0
    if text.startswith("["):
        host, _, rest = text[1].partition("]")
        port_text = rest.lstrip(":")
        return host, pacs_safe_int(port_text, 0)
    # 从右往左切最后一个冒号（避免 IPv6 裸写误判）
    if text.count(":") == 1:
        host, _, port_text = text.partition(":")
        return host.strip(), pacs_safe_int(port_text.strip(), 0)
    if ":" in text:
        host, _, port_text = text.rpartition(":")
        if port_text.strip().isdigit():
            return host.strip(), pacs_safe_int(port_text, 0)
    return text, 0


def pacs_is_valid_proxy_address(pms_address: str) -> bool:
    host, port = pacs_split_proxy(pms_address)
    return bool(host) and 0 < port <= 65535


def pacs_cidr_to_mask(pms_cidr: str) -> str:
    """`/24` 之类位数 → `255.255.255.0`；非法输入原样返回。"""
    try:
        bits = int(str(pms_cidr).strip())
    except (TypeError, ValueError):
        return str(pms_cidr)
    if bits < 0 or bits > 32:
        return "255.255.255.255"
    mask = (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF
    return f"{(mask >> 24) & 255}.{(mask >> 16) & 255}.{(mask >> 8) & 255}.{mask & 255}"


def pacs_mask_to_cidr(pms_mask: str) -> str:
    try:
        octets = [int(x) for x in str(pms_mask).split(".")]
        if len(octets) != 4:
            return str(pms_mask)
    except (TypeError, ValueError):
        return str(pms_mask)
    return str(sum(bin(o & 0xFF).count("1") for o in octets))


def pacs_normalize_domain(pms_text: str) -> str:
    """域名归一：去 `*.`、去前导点、小写、去端口与路径。"""
    text = str(pms_text or "").strip().lower()
    if not text:
        return ""
    text = text.split("/")[0].split("?")[0]
    if text.startswith("*."):
        text = text[2:]
    text = text.lstrip(".")
    if text.count(":") == 1:
        text = text.split(":")[0]
    return text.strip(".")


def pacs_uniq_keep_order(pms_items: Sequence[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in pms_items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def pacs_now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def pacs_open_in_explorer(pms_path: Path) -> bool:
    """在资源管理器里打开目录（失败只记日志，不抛）。"""
    try:
        if os.name == "nt":
            os.startfile(str(Path(pms_path)))  # type: ignore[attr-defined]
            return True
        return False
    except Exception as exc:  # noqa: BLE001
        pacs_logger.warning("打开目录失败：%s（%s）", pms_path, exc)
        return False


def pacs_app_title(pms_suffix: str = "") -> str:
    return f"{PACS_APP_NAME} · {pms_suffix}" if pms_suffix else PACS_APP_NAME


def pacs_make_hint_label_style() -> str:
    return "color: #555; font-size: 12px;"


def pacs_text_preview(pms_text: str, pms_limit: int = 60) -> str:
    text = str(pms_text or "").replace("\n", " ")
    return text if len(text) <= pms_limit else text[: pms_limit - 1] + "…"


def pacs_get(pms_dict: Optional[dict], pms_key: str, pms_default: Any = None) -> Any:
    if not isinstance(pms_dict, dict):
        return pms_default
    value = pms_dict.get(pms_key, pms_default)
    return pms_default if value is None else value
