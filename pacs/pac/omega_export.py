# -*- coding: utf-8 -*-
"""规则表 → ZeroOmega 风格 PAC 导出。

产物与 ZeroOmega 导出同构，可直接粘回 ZeroOmega 的「自动切换模式 → PAC 脚本」：

```js
var FindProxyForURL = function(init, profiles) { ... }("+自动模式", {
    "+自动模式": function(url, host, scheme) { ... return "+Master"; },
    "+Master":  function(url, host, scheme) { ... return "SOCKS5 1.2.3.4:8080"; }
});
/* End of PAC */;
```

两种风格：
    compatible —— 与 ZeroOmega 原生导出同构（规则指向 `+Master`，出口单独一个 profile）。
                  多个不同出口自动拆成 `+Master`、`+Master_2`…
    flat       —— 每条规则直接 return 具体代理串，结构最简单，适合贴到别的 PAC 客户端。

导出后必须能被本程序的导入器原样读回（往返一致性由冒烟脚本校验）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_APP_NAME,
    PACS_APP_VERSION,
    PACS_MATCH_ALL,
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_DOMAIN_WILDCARD,
    PACS_MATCH_HOST_REGEX,
    PACS_MATCH_IP_CIDR,
    PACS_MATCH_KEYWORD,
    PACS_MATCH_URL_REGEX,
    PACS_OMEGA_ENTRY_NAME,
    PACS_OMEGA_MASTER_NAME,
)
from pacs.pac.model import PacsDocument, PacsRule, pacs_build_token
from pacs.utils import pacs_js_string_literal, pacs_now_text

PacsProgress = Optional[Callable[[int, str], None]]

#: ZeroOmega 的 FindProxyForURL 外壳（与样本逐字一致，含 `+` 前缀跳转语义）
_OMEGA_SHELL = """var FindProxyForURL = function(init, profiles) {
    return function(url, host) {
        "use strict";
        var result = init, scheme = url.substr(0, url.indexOf(":"));
        do {
            if (!profiles[result]) return result;
            result = profiles[result];
            if (typeof result === "function") result = result(url, host, scheme);
        } while (typeof result !== "string" || result.charCodeAt(0) === 43);
        return result;
    };
}("""

#: ZeroOmega 出口 profile 里的本机直连保护（与样本一致）
_LOCAL_GUARD = (
    '        if (/^127\\.0\\.0\\.1$/.test(host) || /^::1$/.test(host) || /^localhost$/.test(host)) '
    'return "DIRECT";'
)


@dataclass
class PacsOmegaExportResult:
    text: str = ""
    style: str = "compatible"
    rule_count: int = 0
    master_count: int = 0
    warnings: list[str] = field(default_factory=list)
    size_bytes: int = 0
    elapsed_ms: float = 0.0


def pacs_export_omega(
    pms_document: PacsDocument,
    pms_style: str = "compatible",
    pms_escape_unicode: bool = True,
    pms_progress: PacsProgress = None,
) -> PacsOmegaExportResult:
    started = time.perf_counter()
    style = pms_style if pms_style in ("compatible", "flat") else "compatible"
    result = PacsOmegaExportResult(style=style)
    rules = [rule for rule in pms_document.pacs_enabled_rules()]
    result.rule_count = len(rules)
    _notify(pms_progress, 10, f"准备导出 {len(rules)} 条规则…")

    default_token = pms_document.pacs_effective_default_token()
    # 出口 → profile 名（compatible 风格）
    outlets: dict[str, str] = {}
    if style == "compatible":
        outlets[default_token] = PACS_OMEGA_MASTER_NAME
    lines: list[str] = []
    total = max(1, len(rules))

    for index, rule in enumerate(rules, start=1):
        if index % 400 == 0:
            _notify(pms_progress, 10 + int(70 * index / total), f"导出规则 {index}/{total}")
        condition = _omega_condition(rule)
        if not condition:
            result.warnings.append(f"第 {index} 条规则无法导出（匹配内容为空），已跳过")
            continue
        token = _omega_token(rule, pms_document)
        if style == "compatible":
            if token == PACS_ACTION_DIRECT:
                target = PACS_ACTION_DIRECT
            else:
                if token not in outlets:
                    suffix = "" if len(outlets) == 0 else f"_{len(outlets) + 1}"
                    outlets[token] = PACS_OMEGA_MASTER_NAME + suffix
                target = outlets[token]
            lines.append(f'        if ({condition}) return {pacs_js_string_literal(target, pms_escape_unicode)};')
        else:
            lines.append(f'        if ({condition}) return {pacs_js_string_literal(token, pms_escape_unicode)};')
        if rule.match == PACS_MATCH_ALL:
            result.warnings.append("「全部流量」规则之后的内容不会命中（导出时保留顺序）")

    # 默认动作
    if style == "compatible":
        if default_token == PACS_ACTION_DIRECT:
            default_line = '        return "DIRECT";'
        else:
            if default_token not in outlets:
                outlets[default_token] = PACS_OMEGA_MASTER_NAME
            default_line = f'        return {pacs_js_string_literal(outlets[default_token], pms_escape_unicode)};'
    else:
        default_line = f"        return {pacs_js_string_literal(default_token, pms_escape_unicode)};"

    _notify(pms_progress, 85, "拼装 ZeroOmega 结构…")
    body: list[str] = []
    body.append("/* ============================================================================")
    body.append(f" * {PACS_APP_NAME}（PAC Studio）v{PACS_APP_VERSION} 导出 · ZeroOmega 兼容格式")
    body.append(f" * 方案：{pms_document.name} · 规则 {len(rules)} 条 · 导出时间：{pacs_now_text()}")
    body.append(f" * 风格：{'compatible（与 ZeroOmega 原生导出一致）' if style == 'compatible' else 'flat（直接返回代理串）'}")
    body.append(" * 用法：复制全文，粘贴到 ZeroOmega 的「自动切换模式 → PAC 脚本」里，保存并应用。")
    body.append(" * ==========================================================================*/")
    body.append("")
    body.append(_OMEGA_SHELL + pacs_js_string_literal(PACS_OMEGA_ENTRY_NAME, pms_escape_unicode) + ", {")
    body.append(f'    {pacs_js_string_literal(PACS_OMEGA_ENTRY_NAME, pms_escape_unicode)}: function(url, host, scheme) {{')
    body.append('        "use strict";')
    body.extend(lines)
    body.append(default_line)
    body.append("    }")

    if style == "compatible":
        for token, master_name in outlets.items():
            if token == PACS_ACTION_DIRECT:
                continue
            body.append("    ,")
            body.append(f'    {pacs_js_string_literal(master_name, pms_escape_unicode)}: function(url, host, scheme) {{')
            body.append('        "use strict";')
            body.append(_LOCAL_GUARD)
            body.append(f"        return {pacs_js_string_literal(token, pms_escape_unicode)};")
            body.append("    }")
        result.master_count = sum(1 for token in outlets if token != PACS_ACTION_DIRECT)

    body.append("});")
    body.append("")
    body.append("/* End of PAC */;")
    body.append("")

    result.text = "\n".join(body)
    result.size_bytes = len(result.text.encode("utf-8"))
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    _notify(pms_progress, 100, f"导出完成：{result.size_bytes / 1024:.1f} KB")
    return result


# --------------------------------------------------------------------------------------
# 条件与动作
# --------------------------------------------------------------------------------------
def _omega_condition(pms_rule: PacsRule) -> str:
    """规则 → ZeroOmega 里的判断条件（`/re/.test(host)` 等）。"""
    if pms_rule.match == PACS_MATCH_ALL:
        return 'true'
    if pms_rule.match == PACS_MATCH_DOMAIN_SUFFIX:
        domain = _escape_js_regex(pms_rule.content.lower())
        return f"/(?:^|\\.){domain}$/.test(host)" if "/" not in domain else f"/^(?:.*\\.)?{domain}$/.test(host)"
    if pms_rule.match == PACS_MATCH_DOMAIN_WILDCARD:
        return _wildcard_regex(pms_rule.content)
    if pms_rule.match == PACS_MATCH_KEYWORD:
        # url 一定包含 host，所以测 url 即可同时覆盖域名与路径里的关键词
        return f"/{_escape_js_regex(pms_rule.content)}/i.test(url)"
    if pms_rule.match == PACS_MATCH_URL_REGEX:
        return f"/{_literal_pattern(pms_rule.content)}/.test(url)"
    if pms_rule.match == PACS_MATCH_HOST_REGEX:
        return f"/{_literal_pattern(pms_rule.content)}/.test(host)"
    if pms_rule.match == PACS_MATCH_IP_CIDR:
        ip, mask = pms_rule.pacs_ip_parts()
        return f'isInNet(host, "{ip}", "{mask}")'
    return ""


def _omega_token(pms_rule: PacsRule, pms_document: PacsDocument) -> str:
    if pms_rule.action == PACS_ACTION_DIRECT:
        return PACS_ACTION_DIRECT
    return pacs_build_token(
        pms_rule.action,
        pms_rule.proxy or pms_document.default_proxy,
        pms_document.mixed_add_direct_fallback or pms_rule.fallback_direct,
    )


def _escape_js_regex(pms_text: str) -> str:
    """把普通文本转成正则字面量内容（转义正则元字符与 `/`）。"""
    out: list[str] = []
    for char in str(pms_text or ""):
        if char in r".+?^$()[]{}|\\":
            out.append("\\" + char)
        elif char == "/":
            out.append("\\/")
        else:
            out.append(char)
    return "".join(out)


def _literal_pattern(pms_pattern: str) -> str:
    """已有正则：只把未转义的 `/` 转义，避免破坏字面量边界。"""
    out: list[str] = []
    prev = ""
    for char in str(pms_pattern or ""):
        if char == "/" and prev != "\\":
            out.append("\\/")
        else:
            out.append(char)
        prev = char
    return "".join(out)


def _wildcard_regex(pms_pattern: str) -> str:
    text = str(pms_pattern or "").strip().lower()
    if text.startswith("*."):
        rest = _escape_js_regex(text[2:])
        return f"/(?:^|\\.)(?:.*\\.)?{rest}$/.test(host)"
    parts: list[str] = []
    for char in text:
        if char == "*":
            parts.append(".*")
        elif char in r".+?^$()[]{}|\\":
            parts.append("\\" + char)
        else:
            parts.append(char)
    return "/^(?:.*\\.)?" + "".join(parts) + "$/.test(host)"


def _notify(pms_progress: PacsProgress, pms_percent: int, pms_message: str) -> None:
    if pms_progress is None:
        return
    try:
        pms_progress(max(0, min(100, int(pms_percent))), pms_message)
    except Exception:  # noqa: BLE001
        pass
