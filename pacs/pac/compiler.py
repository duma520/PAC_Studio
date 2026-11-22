# -*- coding: utf-8 -*-
"""规则 → PAC 脚本编译器。

两种产物：
    readable  —— 逐条 `if`，和手工写的 PAC 一样，便于人看、便于排查；
    optimized —— 域名规则合并成「后缀哈希表 + 逐级去前缀」，几千条规则也只做
                 4~6 次对象查找；其余类型按段生成数组循环。**规则顺序语义完全保留**
                 （相邻同类型规则并成一段，段与段之间仍是先后执行）。

关键语义（与 Proxy_Manager_Studio 的 PAC 编辑器一致，便于互相理解）：
    - `baidu.com` 覆盖 baidu.com 自身与所有子域（等价 `*.baidu.com`）；
    - 本机 / 内网 / 纯主机名一律直连，避免访问本机服务绕进代理；
    - 命中第一条规则立即返回，后面的规则不再判断；
    - 「全部流量」规则之后的内容不可达，编译时截断并给出警告。

编码约定：PAC 文件正文用 UTF-8 写；**所有进入字符串字面量的内容一律转成 \\uXXXX**
（默认开启），这样即使某些引擎按 ANSI 读取 PAC 文件，规则值也不会被编码破坏；
中文只出现在注释里，注释乱码不影响脚本解析。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_MIXED,
    PACS_MATCH_ALL,
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_DOMAIN_WILDCARD,
    PACS_MATCH_HOST_REGEX,
    PACS_MATCH_IP_CIDR,
    PACS_MATCH_KEYWORD,
    PACS_MATCH_LABELS,
    PACS_MATCH_URL_REGEX,
    PACS_APP_NAME,
    PACS_APP_VERSION,
    PACS_COMPILE_OPTIMIZED,
    PACS_COMPILE_READABLE,
)
from pacs.pac.model import PacsDocument, PacsRule, pacs_build_token
from pacs.utils import pacs_js_string_literal, pacs_normalize_domain, pacs_now_text

#: 进度回调：(百分比 0~100, 中文说明) -> None
PacsProgress = Optional[Callable[[int, str], None]]

#: 判断 host 是否为 IPv4 字面量（避免 isInNet 对域名做 DNS 解析）
_IPV4_TEST = r"/^\d+\.\d+\.\d+\.\d+$/"

#: 优化版每段最多合并的域名数（单个 map 太大时拆段，避免个别引擎解析超时）
_OPT_DOMAIN_CHUNK = 2000


@dataclass
class PacsCompileResult:
    text: str = ""
    mode: str = PACS_COMPILE_OPTIMIZED
    rule_count: int = 0
    enabled_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = field(default_factory=list)
    size_bytes: int = 0
    elapsed_ms: float = 0.0

    def pacs_summary(self) -> str:
        return (
            f"{'优化版' if self.mode == PACS_COMPILE_OPTIMIZED else '可读版'} · "
            f"规则 {self.enabled_count}/{self.rule_count} 条 · "
            f"{self.size_bytes / 1024:.1f} KB · {self.elapsed_ms:.0f} ms"
        )


# --------------------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------------------
def pacs_compile(
    pms_document: PacsDocument,
    pms_mode: str = PACS_COMPILE_OPTIMIZED,
    pms_escape_unicode: bool = True,
    pms_progress: PacsProgress = None,
) -> PacsCompileResult:
    """把一份方案编译成完整 PAC 脚本。永不抛异常（错误进 warnings）。"""
    started = time.perf_counter()
    mode = pms_mode if pms_mode in (PACS_COMPILE_OPTIMIZED, PACS_COMPILE_READABLE) else PACS_COMPILE_OPTIMIZED
    result = PacsCompileResult(mode=mode, rule_count=len(pms_document.rules))
    _notify(pms_progress, 2, "整理规则…")

    rules: list[PacsRule] = []
    for rule in pms_document.pacs_enabled_rules():
        normalized, warning = _normalize_rule(rule, pms_document)
        if warning:
            result.warnings.append(warning)
        if normalized is None:
            result.skipped_count += 1
            continue
        rules.append(normalized)
    result.enabled_count = len(rules)
    _notify(pms_progress, 12, f"整理完成，共 {len(rules)} 条启用规则")

    default_token = pms_document.pacs_effective_default_token()
    if pms_document.default_action == "proxy" and default_token == "DIRECT":
        result.warnings.append("默认动作是「走代理」但方案里没有默认代理地址，已退化为直连")

    groups = _pacs_group_rules(rules, result)
    _notify(pms_progress, 20, f"编译 {len(groups)} 个规则段…")

    if mode == PACS_COMPILE_READABLE:
        body = _pacs_build_readable(groups, default_token, pms_escape_unicode, result, pms_progress)
    else:
        body = _pacs_build_optimized(groups, default_token, pms_escape_unicode, result, pms_progress)

    header = _pacs_build_header(pms_document, result, default_token)
    result.text = header + body
    result.size_bytes = len(result.text.encode("utf-8"))
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    _notify(pms_progress, 100, f"编译完成：{result.size_bytes / 1024:.1f} KB")
    return result


# --------------------------------------------------------------------------------------
# 规则预处理
# --------------------------------------------------------------------------------------
def _normalize_rule(pms_rule: PacsRule, pms_document: PacsDocument) -> tuple[Optional[PacsRule], str]:
    """归一 + 兜底代理地址；无法编译的返回 (None, 警告)。"""
    rule = pms_rule.pacs_clone()
    if not rule.enabled:
        return None, ""

    if rule.match == PACS_MATCH_DOMAIN_SUFFIX:
        domain = pacs_normalize_domain(rule.content)
        if not domain:
            return None, f"域名规则内容为空或非法，已跳过：{rule.content!r}"
        rule.content = domain
    elif rule.match == PACS_MATCH_DOMAIN_WILDCARD:
        text = str(rule.content or "").strip().lower().lstrip(".")
        if not text:
            return None, "通配域名规则内容为空，已跳过"
        rule.content = text
    elif rule.match in (PACS_MATCH_URL_REGEX, PACS_MATCH_HOST_REGEX):
        text = str(rule.content or "").strip()
        if not text:
            return None, "正则规则内容为空，已跳过"
        try:
            re.compile(text)
        except re.error as exc:
            return None, f"正则写错，已跳过：{text!r}（{exc}）"
        rule.content = text
    elif rule.match == PACS_MATCH_KEYWORD:
        text = str(rule.content or "").strip()
        if not text:
            return None, "关键词规则内容为空，已跳过"
        rule.content = text
    elif rule.match == PACS_MATCH_IP_CIDR:
        ip, mask = rule.pacs_ip_parts()
        if not ip:
            return None, "IP 段规则内容为空，已跳过"
        rule.content = f"{ip}/{mask}" if "/" in str(rule.content) else ip
    elif rule.match != PACS_MATCH_ALL:
        return None, f"未知匹配类型，已跳过：{rule.match}"

    # 动作 → 返回串（走代理但没填地址时用方案默认地址兜底）
    if rule.action != PACS_ACTION_DIRECT:
        addr = str(rule.proxy or "").strip() or str(pms_document.default_proxy or "").strip()
        if not addr:
            rule.action = PACS_ACTION_DIRECT
            return rule, f"规则「{rule.content}」走代理但没地址，已退化为直连"
        rule.proxy = addr
    return rule, ""


def _pacs_group_rules(pms_rules: list[PacsRule], pms_result: PacsCompileResult) -> list[tuple[str, list[PacsRule]]]:
    """把相邻同类型规则并成一段；保持原有先后顺序。"""
    groups: list[tuple[str, list[PacsRule]]] = []
    for rule in pms_rules:
        if groups and groups[-1][0] == rule.match:
            groups[-1][1].append(rule)
        else:
            groups.append((rule.match, [rule]))
        if rule.match == PACS_MATCH_ALL:
            if len(pms_rules) > sum(len(items) for _kind, items in groups):
                pms_result.warnings.append("「全部流量」规则之后还有规则，后面的规则永远不会命中（已忽略）")
            break
    return groups


# --------------------------------------------------------------------------------------
# 变量名 / 字面量工具
# --------------------------------------------------------------------------------------
def _pacs_rule_token(pms_rule: PacsRule, pms_document: PacsDocument) -> str:
    if pms_rule.action == PACS_ACTION_DIRECT:
        return PACS_ACTION_DIRECT
    return pacs_build_token(pms_rule.action, pms_rule.proxy, pms_document.mixed_add_direct_fallback)


def _js(pms_text: str, pms_escape_unicode: bool) -> str:
    return pacs_js_string_literal(pms_text, pms_escape_unicode)


def _regex_literal(pms_pattern: str) -> str:
    """把 Python 校验过的正则写成 JS 正则字面量（转义未转义的 `/`）。"""
    out: list[str] = []
    prev = ""
    for ch in pms_pattern:
        if ch == "/" and prev != "\\":
            out.append("\\/")
        else:
            out.append(ch)
        prev = ch
    return "/" + "".join(out) + "/"


def _regex_string(pms_pattern: str, pms_escape_unicode: bool) -> str:
    """把正则写成 `new RegExp("...")` 里的字符串（比字面量更抗转义问题）。"""
    return "new RegExp(" + pacs_js_string_literal(pms_pattern, pms_escape_unicode) + ")"


def _wildcard_to_regex(pms_pattern: str) -> str:
    """通配域名 → 主机名正则。

    `*.example.com` 语义与域名后缀一致：命中 example.com 自身与其所有子域。
    其它位置的 `*` 按「任意字符（含点）」处理。
    """
    text = str(pms_pattern or "").strip().lower()
    prefix = ""
    if text.startswith("*."):
        prefix = "^(?:.*\\.)?"
        text = text[2:]
    else:
        prefix = "^"
    parts: list[str] = []
    for ch in text:
        if ch == "*":
            parts.append(".*")
        elif ch in r".+?^$()[]{}|\\":
            parts.append("\\" + ch)
        else:
            parts.append(ch)
    return prefix + "".join(parts) + "$"


def _reverse_for_map(pms_domain: str) -> str:
    """域名后缀表的键直接存域名本身（查找时逐级去前缀即可命中）。"""
    return pms_domain


def _notify(pms_progress: PacsProgress, pms_percent: int, pms_message: str) -> None:
    if pms_progress is None:
        return
    try:
        pms_progress(max(0, min(100, int(pms_percent))), pms_message)
    except Exception:  # noqa: BLE001 进度回调失败不能影响编译
        pass


# --------------------------------------------------------------------------------------
# 头部注释
# --------------------------------------------------------------------------------------
def _pacs_build_header(
    pms_document: PacsDocument,
    pms_result: PacsCompileResult,
    pms_default_token: str,
) -> str:
    stats = pms_document.pacs_stats()
    lines = [
        "// ============================================================================",
        f"// {PACS_APP_NAME}（PAC Studio）v{PACS_APP_VERSION} · 自动生成，手工修改会在下次编译时被覆盖",
        f"// 方案：{pms_document.name}",
        f"// 规则：启用 {stats.get('enabled', 0)} / 共 {stats.get('total', 0)} 条"
        f"（直连 {stats.get('direct_rules', 0)} 条，走代理 {stats.get('proxy_rules', 0)} 条）",
        f"// 默认动作：{'走代理' if pms_document.default_action == 'proxy' else '直连'} → {pms_default_token}",
        "// 本机 / 内网 / 纯主机名一律直连，不参与下面的规则判断。",
        f"// 生成时间：{pacs_now_text()} · 编译模式：{'优化版' if pms_result.mode == PACS_COMPILE_OPTIMIZED else '可读版'}",
        "// ============================================================================",
        "",
        "var PACS_DEFAULT = " + _js(pms_default_token, True) + ";",
        "",
    ]
    for index, warning in enumerate(pms_result.warnings[:20], start=1):
        lines.append(f"// [警告 {index}] {warning}")
    if pms_result.warnings:
        lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# 可读版
# --------------------------------------------------------------------------------------
def _pacs_build_readable(
    pms_groups: list[tuple[str, list[PacsRule]]],
    pms_default_token: str,
    pms_escape_unicode: bool,
    pms_result: PacsCompileResult,
    pms_progress: PacsProgress,
) -> str:
    del pms_default_token  # 默认值走 PACS_DEFAULT 变量
    lines: list[str] = [
        "function FindProxyForURL(url, host) {",
        '    host = (host || "").toLowerCase();',
        '    var lower_url = (url || "").toLowerCase();',
        '    if (isPlainHostName(host) || host === "localhost" || host === "127.0.0.1" || host === "::1") {',
        '        return "DIRECT";',
        "    }",
        "",
    ]
    total = max(1, len(pms_groups))
    for index, (kind, rules) in enumerate(pms_groups, start=1):
        _notify(pms_progress, 20 + int(70 * index / total), f"可读版：{PACS_MATCH_LABELS.get(kind, kind)} {len(rules)} 条")
        lines.append(f"    // ---- 段 {index}：{PACS_MATCH_LABELS.get(kind, kind)}（{len(rules)} 条）")
        if kind == PACS_MATCH_IP_CIDR:
            lines.append(f"    if ({_IPV4_TEST}.test(host)) {{")
        for rule in rules:
            token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
            lines.append("    " + _readable_condition(kind, rule, token, pms_escape_unicode))
        if kind == PACS_MATCH_IP_CIDR:
            lines.append("    }")
        lines.append("")
    lines.append("    return PACS_DEFAULT;")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _doc_proxy_placeholder(pms_rule: PacsRule) -> PacsDocument:
    """可读版生成 token 时只需要动作+地址，用最小文档占位（避免多传参数）。"""
    return PacsDocument(
        default_proxy=pms_rule.proxy,
        default_scheme=PACS_ACTION_MIXED if pms_rule.action == PACS_ACTION_MIXED else pms_rule.action,
        mixed_add_direct_fallback=pms_rule.fallback_direct,
    )


def _readable_condition(
    pms_kind: str,
    pms_rule: PacsRule,
    pms_token: str,
    pms_escape_unicode: bool,
) -> str:
    token_literal = _js(pms_token, pms_escape_unicode)
    if pms_kind == PACS_MATCH_DOMAIN_SUFFIX:
        domain = pms_rule.content
        return (
            f'if (dnsDomainIs(host, ".{domain}") || host === {_js(domain, False)}) '
            f"{{ return {token_literal}; }}"
        )
    if pms_kind == PACS_MATCH_DOMAIN_WILDCARD:
        regex = _wildcard_to_regex(pms_rule.content)
        return f"if ({_regex_literal(regex)}.test(host)) {{ return {token_literal}; }}"
    if pms_kind == PACS_MATCH_KEYWORD:
        kw = _js(pms_rule.content.lower(), pms_escape_unicode)
        return (
            f"if (host.indexOf({kw}) >= 0 || lower_url.indexOf({kw}) >= 0) "
            f"{{ return {token_literal}; }}"
        )
    if pms_kind == PACS_MATCH_URL_REGEX:
        return f"if ({_regex_literal(pms_rule.content)}.test(url)) {{ return {token_literal}; }}"
    if pms_kind == PACS_MATCH_HOST_REGEX:
        return f"if ({_regex_literal(pms_rule.content)}.test(host)) {{ return {token_literal}; }}"
    if pms_kind == PACS_MATCH_IP_CIDR:
        ip, mask = pms_rule.pacs_ip_parts()
        return f'if (isInNet(host, "{ip}", "{mask}")) {{ return {token_literal}; }}'
    # 全部流量
    return f"return {token_literal};"


# --------------------------------------------------------------------------------------
# 优化版
# --------------------------------------------------------------------------------------
def _pacs_build_optimized(
    pms_groups: list[tuple[str, list[PacsRule]]],
    pms_default_token: str,
    pms_escape_unicode: bool,
    pms_result: PacsCompileResult,
    pms_progress: PacsProgress,
) -> str:
    del pms_default_token
    vars_block: list[str] = []
    body: list[str] = []
    total = max(1, len(pms_groups))

    for group_index, (kind, rules) in enumerate(pms_groups, start=1):
        _notify(pms_progress, 20 + int(70 * group_index / total), f"优化版：{PACS_MATCH_LABELS.get(kind, kind)} {len(rules)} 条")
        if kind == PACS_MATCH_IP_CIDR:
            # IP 段保持顺序（数量通常很少）
            body.append(f"    // ---- 段 {group_index}：IP 段（{len(rules)} 条）")
            body.append(f"    if ({_IPV4_TEST}.test(host)) {{")
            for rule in rules:
                ip, mask = rule.pacs_ip_parts()
                token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
                body.append(f'        if (isInNet(host, "{ip}", "{mask}")) {{ return {_js(token, pms_escape_unicode)}; }}')
            body.append("    }")
            body.append("")
            continue

        if kind == PACS_MATCH_ALL:
            rule = rules[0]
            token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
            body.append(f"    // ---- 段 {group_index}：全部流量（其后规则不可达）")
            body.append(f"    return {_js(token, pms_escape_unicode)};")
            body.append("")
            continue

        if kind == PACS_MATCH_DOMAIN_SUFFIX:
            chunks = _chunk(rules, _OPT_DOMAIN_CHUNK)
            for chunk_index, chunk in enumerate(chunks, start=1):
                var = f"PACS_DOM_{group_index}_{chunk_index}"
                mapping = _build_domain_map(chunk, pms_escape_unicode)
                vars_block.append(f"var {var} = {{\n" + ",\n".join(f"    {k}: {v}" for k, v in mapping) + "\n};")
                body.append(f"    // ---- 段 {group_index}.{chunk_index}：域名后缀查表（{len(chunk)} 条）")
                body.append("    {")
                body.append("        var d = host, dot;")
                body.append("        while (true) {")
                body.append(f"            if ({var}[d]) return {var}[d];")
                body.append('            dot = d.indexOf(".");')
                body.append("            if (dot < 0) break;")
                body.append("            d = d.substring(dot + 1);")
                body.append("        }")
                body.append("    }")
                body.append("")
            continue

        if kind == PACS_MATCH_DOMAIN_WILDCARD:
            var = f"PACS_WILD_{group_index}"
            rows = []
            for rule in rules:
                regex = _wildcard_to_regex(rule.content)
                token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
                rows.append(f"    [{_regex_string(regex, pms_escape_unicode)}, {_js(token, pms_escape_unicode)}]")
            vars_block.append(f"var {var} = [\n" + ",\n".join(rows) + "\n];")
            body.append(f"    // ---- 段 {group_index}：通配域名（{len(rules)} 条）")
            body.append(f"    for (var w{_idx_var(group_index)} = 0; w{_idx_var(group_index)} < {var}.length; w{_idx_var(group_index)}++) {{")
            body.append(f"        if ({var}[w{_idx_var(group_index)}][0].test(host)) return {var}[w{_idx_var(group_index)}][1];")
            body.append("    }")
            body.append("")
            continue

        if kind == PACS_MATCH_KEYWORD:
            var = f"PACS_KW_{group_index}"
            flat: list[str] = []
            for rule in rules:
                token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
                flat.append(_js(rule.content.lower(), pms_escape_unicode))
                flat.append(_js(token, pms_escape_unicode))
            vars_block.append(f"var {var} = [\n    " + ",\n    ".join(flat) + "\n];")
            body.append(f"    // ---- 段 {group_index}：关键词（{len(rules)} 条）")
            body.append(f"    for (var k{_idx_var(group_index)} = 0; k{_idx_var(group_index)} < {var}.length; k{_idx_var(group_index)} += 2) {{")
            body.append(
                f"        if (host.indexOf({var}[k{_idx_var(group_index)}]) >= 0"
                f" || lower_url.indexOf({var}[k{_idx_var(group_index)}]) >= 0)"
                f" return {var}[k{_idx_var(group_index)} + 1];"
            )
            body.append("    }")
            body.append("")
            continue

        if kind in (PACS_MATCH_URL_REGEX, PACS_MATCH_HOST_REGEX):
            var = f"PACS_RE_{group_index}"
            target = "url" if kind == PACS_MATCH_URL_REGEX else "host"
            rows = []
            for rule in rules:
                token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
                rows.append(f"    [{_regex_string(rule.content, pms_escape_unicode)}, {_js(token, pms_escape_unicode)}]")
            vars_block.append(f"var {var} = [\n" + ",\n".join(rows) + "\n];")
            body.append(f"    // ---- 段 {group_index}：{PACS_MATCH_LABELS.get(kind)}（{len(rules)} 条）")
            body.append(f"    for (var r{_idx_var(group_index)} = 0; r{_idx_var(group_index)} < {var}.length; r{_idx_var(group_index)}++) {{")
            body.append(f"        if ({var}[r{_idx_var(group_index)}][0].test({target})) return {var}[r{_idx_var(group_index)}][1];")
            body.append("    }")
            body.append("")
            continue

    head: list[str] = []
    if vars_block:
        head.append("\n\n".join(vars_block))
        head.append("")
    head.extend([
        "function FindProxyForURL(url, host) {",
        '    host = (host || "").toLowerCase();',
        '    var lower_url = (url || "").toLowerCase();',
        '    if (isPlainHostName(host) || host === "localhost" || host === "127.0.0.1" || host === "::1") {',
        '        return "DIRECT";',
        "    }",
        "",
    ])
    tail = ["    return PACS_DEFAULT;", "}", ""]
    return "\n".join(head + body + tail)


def _idx_var(pms_index: int) -> str:
    return str(pms_index)


def _chunk(pms_items: list[PacsRule], pms_size: int) -> list[list[PacsRule]]:
    if pms_size <= 0:
        return [pms_items]
    return [pms_items[i : i + pms_size] for i in range(0, len(pms_items), pms_size)]


def _build_domain_map(pms_rules: list[PacsRule], pms_escape_unicode: bool) -> list[tuple[str, str]]:
    """域名 → token 映射，**先出现的规则优先**（同域重复时后者忽略）。"""
    seen: dict[str, str] = {}
    for rule in pms_rules:
        key = _js(_reverse_for_map(rule.content), pms_escape_unicode)
        if key in seen:
            continue
        token = _pacs_rule_token(rule, _doc_proxy_placeholder(rule))
        seen[key] = _js(token, pms_escape_unicode)
    return list(seen.items())
