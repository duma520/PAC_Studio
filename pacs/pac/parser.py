# -*- coding: utf-8 -*-
"""PAC 脚本 → 规则（反解析）。

支持三种来源：
    1. 本程序「可读版」产物（逐条 if）；
    2. 本程序「优化版」产物（域名查表 + 数组段）；
    3. Proxy_Manager_Studio 的 `PMS_PROXY` / `PMS_DEFAULT` 风格脚本。
识别不了的脚本返回 `recognized=False`，调用方据此提示用户「规则表保持不变」，
绝不因为解析失败就把用户的规则清空。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_MATCH_ALL,
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_DOMAIN_WILDCARD,
    PACS_MATCH_HOST_REGEX,
    PACS_MATCH_IP_CIDR,
    PACS_MATCH_KEYWORD,
    PACS_MATCH_URL_REGEX,
)
from pacs.pac.model import PacsDocument, PacsRule, pacs_split_token
from pacs.utils import pacs_js_unescape, pacs_mask_to_cidr, pacs_normalize_domain

PacsProgress = Optional[Callable[[int, str], None]]


@dataclass
class PacsParseResult:
    rules: list[PacsRule] = field(default_factory=list)
    default_action: str = "proxy"
    default_proxy: str = ""
    default_scheme: str = PACS_ACTION_SOCKS5
    mixed_fallback_direct: bool = False
    warnings: list[str] = field(default_factory=list)
    recognized: bool = False
    source_format: str = ""

    def pacs_apply_to(self, pms_document: PacsDocument) -> PacsDocument:
        """把解析结果写进一份方案（不动方案名与时间戳）。"""
        doc = pms_document.pacs_clone()
        if self.rules:
            doc.rules = [rule.pacs_clone() for rule in self.rules]
        doc.default_action = self.default_action
        if self.default_proxy:
            doc.default_proxy = self.default_proxy
        doc.default_scheme = self.default_scheme
        doc.mixed_add_direct_fallback = self.mixed_fallback_direct
        return doc


# --------------------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------------------
def pacs_parse_pac(pms_text: str, pms_progress: PacsProgress = None) -> PacsParseResult:
    text = str(pms_text or "")
    result = PacsParseResult()
    if not text.strip():
        result.warnings.append("脚本文本为空")
        return result
    _notify(pms_progress, 5, "识别脚本格式…")

    result = _extract_defaults(text, result)

    if re.search(r"var\s+PACS_DOM_\d+_\d+\s*=", text) or re.search(r"var\s+PACS_WILD_\d+\s*=", text):
        _notify(pms_progress, 25, "解析优化版脚本…")
        ok = _parse_optimized(text, result, pms_progress)
        if ok:
            result.source_format = "optimized"
            result.recognized = True
            _notify(pms_progress, 100, f"解析完成：{len(result.rules)} 条规则")
            return result
        result.warnings.append("优化版脚本解析失败，已改按逐行方式尝试")

    _notify(pms_progress, 40, "解析逐行脚本…")
    ok = _parse_line_based(text, result, pms_progress)
    if ok:
        result.source_format = "line"
        result.recognized = True
    else:
        result.warnings.append("这份脚本不是本程序生成的格式，规则表保持不变（可继续用专业模式直接编辑）")
    _notify(pms_progress, 100, f"解析完成：{len(result.rules)} 条规则")
    return result


# --------------------------------------------------------------------------------------
# 默认值提取
# --------------------------------------------------------------------------------------
def _extract_defaults(pms_text: str, pms_result: PacsParseResult) -> PacsParseResult:
    token = ""
    match = re.search(r'var\s+PACS_DEFAULT\s*=\s*("(?:[^"\\]|\\.)*")\s*;', pms_text)
    if match:
        token = _js_decode(match.group(1))
    else:
        match = re.search(r'var\s+PMS_DEFAULT\s*=\s*\(\s*("(?:[^"\\]|\\.)*")\s*\)\s*;', pms_text)
        if match:
            token = _js_decode(match.group(1))
        else:
            match = re.search(r'var\s+PMS_PROXY\s*=\s*\(\s*("(?:[^"\\]|\\.)*")\s*\)\s*;', pms_text)
            if match:
                token = _js_decode(match.group(1))
    if token:
        action, addr, fallback = pacs_split_token(token)
        if action == PACS_ACTION_DIRECT:
            pms_result.default_action = "direct"
        else:
            pms_result.default_action = "proxy"
            pms_result.default_proxy = addr
            pms_result.default_scheme = action
            pms_result.mixed_fallback_direct = fallback
    return pms_result


# --------------------------------------------------------------------------------------
# 逐行脚本（本程序可读版 / PMS 风格）
# --------------------------------------------------------------------------------------
_RE_DOMAIN = re.compile(r'if\s*\(\s*dnsDomainIs\(host,\s*"\.([^"]+)"\)\s*\|\|\s*host\s*===\s*"([^"]+)"\s*\)\s*\{\s*return\s*("(?:[^"\\]|\\.)*")\s*;')
_RE_TEST = re.compile(r'if\s*\(\s*/(.+)/\.test\((host|url)\)\s*\)\s*\{\s*return\s*("(?:[^"\\]|\\.)*")\s*;')
_RE_KEYWORD = re.compile(r'if\s*\(\s*host\.indexOf\("((?:[^"\\]|\\.)*)"\)\s*>=\s*0\s*\|\|\s*(?:lower_url|url)\.indexOf\("((?:[^"\\]|\\.)*)"\)\s*>=\s*0\s*\)\s*\{\s*return\s*("(?:[^"\\]|\\.)*")\s*;')
_RE_SHEXP = re.compile(r'if\s*\(\s*shExpMatch\((?:host|url),\s*"\*([^"]*)\*"\)\s*\)\s*\{\s*return\s*("(?:[^"\\]|\\.)*")\s*;')
_RE_IP = re.compile(r'if\s*\(\s*isInNet\(host,\s*"([^"]+)"\s*,\s*"([^"]+)"\)\s*\)\s*\{\s*return\s*("(?:[^"\\]|\\.)*")\s*;')
_RE_RETURN = re.compile(r'^\s*return\s+("(?:[^"\\]|\\.)*")\s*;')


def _parse_line_based(pms_text: str, pms_result: PacsParseResult, pms_progress: PacsProgress) -> bool:
    lines = pms_text.splitlines()
    total = max(1, len(lines))
    found = 0
    for index, line in enumerate(lines, start=1):
        if index % 400 == 0:
            _notify(pms_progress, 40 + int(50 * index / total), f"逐行解析 {index}/{total}")
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        match = _RE_DOMAIN.search(stripped)
        if match:
            token = _js_decode(match.group(3))
            _append_rule(pms_result, PACS_MATCH_DOMAIN_SUFFIX, match.group(1), token)
            found += 1
            continue

        match = _RE_KEYWORD.search(stripped)
        if match:
            token = _js_decode(match.group(3))
            _append_rule(pms_result, PACS_MATCH_KEYWORD, _js_decode(match.group(1)), token)
            found += 1
            continue

        match = _RE_SHEXP.search(stripped)
        if match:
            token = _js_decode(match.group(2))
            _append_rule(pms_result, PACS_MATCH_KEYWORD, match.group(1), token)
            found += 1
            continue

        match = _RE_IP.search(stripped)
        if match:
            token = _js_decode(match.group(3))
            cidr = f"{match.group(1)}/{pacs_mask_to_cidr(match.group(2))}"
            _append_rule(pms_result, PACS_MATCH_IP_CIDR, cidr, token)
            found += 1
            continue

        match = _RE_TEST.search(stripped)
        if match:
            pattern = _unescape_regex(match.group(1))
            target = match.group(2)
            token = _js_decode(match.group(3))
            _append_test_rule(pms_result, target, pattern, token)
            found += 1
            continue

        match = _RE_RETURN.match(stripped)
        if match and "PACS_DEFAULT" not in stripped and "PMS_DEFAULT" not in stripped:
            token = _js_decode(match.group(1))
            action, addr, fallback = pacs_split_token(token)
            if action == PACS_ACTION_DIRECT:
                pms_result.default_action = "direct"
            elif not pms_result.default_proxy or pms_result.default_action != "proxy":
                pms_result.default_action = "proxy"
                pms_result.default_proxy = addr
                pms_result.default_scheme = action
                pms_result.mixed_fallback_direct = fallback
            found += 1

    return found > 0


# --------------------------------------------------------------------------------------
# 优化版脚本
# --------------------------------------------------------------------------------------
_RE_OPT_DOM = re.compile(r"var\s+PACS_DOM_(\d+)_(\d+)\s*=\s*\{")
_RE_OPT_WILD = re.compile(r"var\s+PACS_WILD_(\d+)\s*=\s*\[")
_RE_OPT_KW = re.compile(r"var\s+PACS_KW_(\d+)\s*=\s*\[")
_RE_OPT_RE = re.compile(r"var\s+PACS_RE_(\d+)\s*=\s*\[")
_RE_SECTION = re.compile(r"//\s*----\s*段\s*(\d+)(?:\.\d+)?：([^（\n]+)")
_RE_ARRAY_PAIR = re.compile(
    r'\[\s*new\s+RegExp\(\s*("(?:[^"\\]|\\.)*")\s*\)\s*,\s*("(?:[^"\\]|\\.)*")\s*\]'
)


def _parse_optimized(pms_text: str, pms_result: PacsParseResult, pms_progress: PacsProgress) -> bool:
    sections = {int(num): kind.strip() for num, kind in _RE_SECTION.findall(pms_text)}
    total_blocks = len(_RE_OPT_DOM.findall(pms_text)) + len(_RE_OPT_WILD.findall(pms_text)) + len(_RE_OPT_KW.findall(pms_text)) + len(_RE_OPT_RE.findall(pms_text))
    done = 0

    # 1) 域名后缀查表
    for match in _RE_OPT_DOM.finditer(pms_text):
        group_index = int(match.group(1))
        body, _end = _slice_brace(pms_text, match.end() - 1)
        mapping = _json_object(body)
        for domain, token in mapping.items():
            _append_rule(pms_result, PACS_MATCH_DOMAIN_SUFFIX, domain, token)
        done += 1
        _notify(pms_progress, 25 + int(60 * done / max(1, total_blocks)), f"域名表 {len(mapping)} 条")

    # 2) 通配域名
    for match in _RE_OPT_WILD.finditer(pms_text):
        body, _end = _slice_bracket(pms_text, match.end() - 1)
        for regex_str, token_str in _RE_ARRAY_PAIR.findall(body):
            pattern = _unescape_regex(_js_decode(regex_str))
            token = _js_decode(token_str)
            wildcard = _regex_to_wildcard(pattern)
            if wildcard:
                _append_rule(pms_result, PACS_MATCH_DOMAIN_WILDCARD, wildcard, token)
            else:
                _append_rule(pms_result, PACS_MATCH_HOST_REGEX, pattern, token)
        done += 1

    # 3) 关键词
    for match in _RE_OPT_KW.finditer(pms_text):
        body, _end = _slice_bracket(pms_text, match.end() - 1)
        try:
            items = json.loads("[" + body.strip().rstrip(",") + "]")
        except json.JSONDecodeError:
            items = []
        for index in range(0, len(items) - 1, 2):
            _append_rule(pms_result, PACS_MATCH_KEYWORD, str(items[index]), str(items[index + 1]))
        done += 1

    # 4) 正则段
    for match in _RE_OPT_RE.finditer(pms_text):
        group_index = int(match.group(1))
        kind_text = sections.get(group_index, "")
        target = "url" if "URL" in kind_text.upper() else "host"
        body, _end = _slice_bracket(pms_text, match.end() - 1)
        for regex_str, token_str in _RE_ARRAY_PAIR.findall(body):
            pattern = _unescape_regex(_js_decode(regex_str))
            token = _js_decode(token_str)
            _append_test_rule(pms_result, target, pattern, token)
        done += 1

    # 5) 全部流量
    for match in re.finditer(r"//\s*----\s*段\s*\d+：全部流量[^\n]*\n\s*return\s+(\"(?:[^\"\\\\]|\\\\.)*\")\s*;", pms_text):
        _append_rule(pms_result, PACS_MATCH_ALL, "", _js_decode(match.group(1)))

    # 6) IP 段
    for match in re.finditer(r'isInNet\(host,\s*"([^"]+)"\s*,\s*"([^"]+)"\)\s*\)\s*\{\s*return\s+("(?:[^"\\]|\\.)*")\s*;', pms_text):
        cidr = f"{match.group(1)}/{pacs_mask_to_cidr(match.group(2))}"
        _append_rule(pms_result, PACS_MATCH_IP_CIDR, cidr, _js_decode(match.group(3)))

    return len(pms_result.rules) > 0


# --------------------------------------------------------------------------------------
# 规则构造
# --------------------------------------------------------------------------------------
def _append_rule(pms_result: PacsParseResult, pms_match: str, pms_content: str, pms_token: str) -> None:
    action, addr, fallback = pacs_split_token(pms_token)
    rule = PacsRule(
        match=pms_match,
        content=str(pms_content or "").strip(),
        action=action,
        proxy=addr,
        fallback_direct=fallback,
        enabled=True,
    )
    if action == PACS_ACTION_DIRECT:
        rule.proxy = ""
    pms_result.rules.append(rule)
    if addr and not pms_result.default_proxy:
        pms_result.default_proxy = addr
        pms_result.default_scheme = action


def _append_test_rule(pms_result: PacsParseResult, pms_target: str, pms_pattern: str, pms_token: str) -> None:
    """`/re/.test(host|url)` → 尽可能还原成可读的域名/通配规则。"""
    if pms_target == "host":
        domain = _regex_to_domain_suffix(pms_pattern)
        if domain:
            _append_rule(pms_result, PACS_MATCH_DOMAIN_SUFFIX, domain, pms_token)
            return
        wildcard = _regex_to_wildcard(pms_pattern)
        if wildcard:
            _append_rule(pms_result, PACS_MATCH_DOMAIN_WILDCARD, wildcard, pms_token)
            return
        _append_rule(pms_result, PACS_MATCH_HOST_REGEX, pms_pattern, pms_token)
        return
    _append_rule(pms_result, PACS_MATCH_URL_REGEX, pms_pattern, pms_token)


def _regex_to_domain_suffix(pms_pattern: str) -> str:
    """`(?:^|\\.)example\\.com$` / `^\\.example\\.com$` → example.com。"""
    text = str(pms_pattern or "").strip()
    match = re.fullmatch(r"\(\?:\^\|\\\.\)(.+)\$", text)
    if not match:
        match = re.fullmatch(r"\^?\\\.(.+)\$", text)
    if not match:
        return ""
    inner = match.group(1)
    if re.search(r"[\[\](){}|?*+^$]", inner.replace("\\.", ".")):
        return ""
    return pacs_normalize_domain(_unescape_regex(inner))


def _regex_to_wildcard(pms_pattern: str) -> str:
    """`^(?:.*\\.)?example\\.com$` → `*.example.com`；其它形式返回空串。"""
    text = str(pms_pattern or "").strip()
    prefix = r"^(?:.*\.)?"
    if text.startswith(prefix) and text.endswith("$"):
        inner = text[len(prefix) : -1]
        if re.search(r"[\[\](){}|?+^$]", inner.replace("\\.", ".")):
            return ""
        return "*." + _unescape_regex(inner).lower()
    generic = re.fullmatch(r"\^(.*)\$$", text)
    if generic and "*" in generic.group(1):
        inner = generic.group(1)
        if re.search(r"[\[\](){}|?+]", inner.replace("\\.", ".")):
            return ""
        text_out = _unescape_regex(inner)
        text_out = text_out.replace(".*", "*").replace("\\.", ".")
        if "*" in text_out and "/" not in text_out:
            return text_out.lower()
    return ""


# --------------------------------------------------------------------------------------
# 扫描工具
# --------------------------------------------------------------------------------------
def _slice_brace(pms_text: str, pms_open_index: int) -> tuple[str, int]:
    """返回 `{...}` 内部文本与结束位置（跳过字符串 / 注释）。"""
    return _slice_pair(pms_text, pms_open_index, "{", "}")


def _slice_bracket(pms_text: str, pms_open_index: int) -> tuple[str, int]:
    return _slice_pair(pms_text, pms_open_index, "[", "]")


def _slice_pair(pms_text: str, pms_open_index: int, pms_open: str, pms_close: str) -> tuple[str, int]:
    if pms_open_index >= len(pms_text) or pms_text[pms_open_index] != pms_open:
        return "", pms_open_index
    depth = 0
    index = pms_open_index
    length = len(pms_text)
    while index < length:
        char = pms_text[index]
        if char == '"' or char == "'":
            index = _skip_string(pms_text, index)
            continue
        if char == "/" and index + 1 < length and pms_text[index + 1] == "/":
            newline = pms_text.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if char == "/" and index + 1 < length and pms_text[index + 1] == "*":
            end = pms_text.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if char == pms_open:
            depth += 1
        elif char == pms_close:
            depth -= 1
            if depth == 0:
                return pms_text[pms_open_index + 1 : index], index
        index += 1
    return pms_text[pms_open_index + 1 :], length


def _skip_string(pms_text: str, pms_index: int) -> int:
    quote = pms_text[pms_index]
    index = pms_index + 1
    length = len(pms_text)
    while index < length:
        char = pms_text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return length


def _js_decode(pms_literal: str) -> str:
    """`"\\u4e2d\\u6587"` → 中文。"""
    text = str(pms_literal or "").strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return pacs_js_unescape(text[1:-1])
    return pacs_js_unescape(text)


def _unescape_regex(pms_pattern: str) -> str:
    return str(pms_pattern or "").replace("\\/", "/")


def _json_object(pms_body: str) -> dict[str, str]:
    text = pms_body.strip().rstrip(",")
    try:
        data = json.loads("{" + text + "}")
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def _notify(pms_progress: PacsProgress, pms_percent: int, pms_message: str) -> None:
    if pms_progress is None:
        return
    try:
        pms_progress(max(0, min(100, int(pms_percent))), pms_message)
    except Exception:  # noqa: BLE001
        pass
