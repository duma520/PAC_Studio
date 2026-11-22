# -*- coding: utf-8 -*-
"""ZeroOmega PAC → 规则表导入。

ZeroOmega（SwitchyOmega 后继）导出的 PAC 结构（以 `G:\\PAC\\OmegaProfile.pac` 实测为准）：

```js
var FindProxyForURL = function(init, profiles) {
    return function(url, host) { ... while (result 以 '+' 开头就继续跳转) ... };
}("+自动模式", {
    "+自动模式": function(url, host, scheme) {
        if (/(?:^|\\.)youtube\\.com$/.test(host)) return "+Master";
        ...
        return "+__ruleListOf_自动模式";          // 兜底指向「规则列表」
    },
    "+__ruleListOf_自动模式": function() {
        var FindProxyForURL = function(init, profiles) { ... }("+__tempZeroRuleListPac", {
            "+__tempZeroRuleListPac": function(url, host, scheme) { ...4416 条... return "DIRECT"; }
        });
        return FindProxyForURL;
    }.call(this),
    "+Master": function(url, host, scheme) {
        if (/^127\\.0\\.0\\.1$/.test(host) || ...) return "DIRECT";
        return "SOCKS5 ***已脱敏***-内网IP:20808";
    }
});
```

因此导入必须做三件事：
    1. **全局收集所有 profile**（含嵌套在别的 profile 里定义的那一套，嵌套的 profile 名唯一）；
    2. **按 `+名字` 跳转链递归展开**（带环检测），把「发往 +Master 的跳转」折叠成具体代理动作；
    3. 对 host 正则做「能安全还原就还原成域名/通配规则，否则保留主机名正则」的归一，
       对 url 正则保留原样（PAC 标准函数，Chrome/Edge/Firefox 都支持）。

任何无法转换的语句都进 `unsupported` 报告，绝不静默丢弃。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_MATCH_ALL,
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_DOMAIN_WILDCARD,
    PACS_MATCH_HOST_REGEX,
    PACS_MATCH_URL_REGEX,
)
from pacs.pac.model import PacsDocument, PacsRule, pacs_split_token
from pacs.utils import pacs_js_unescape, pacs_mask_to_cidr, pacs_normalize_domain

PacsProgress = Optional[Callable[[int, str], None]]

#: profile 定义：`"name": function(args) {`
_RE_PROFILE_DEF = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*function\s*\(([^)]*)\)\s*\{')

#: 嵌套 PAC 的入口：`}("+xxx", {`
_RE_NESTED_ENTRY = re.compile(r'\}\s*\(\s*"((?:[^"\\]|\\.)*)"\s*,\s*\{')

#: 顶层 return：`return "+Master";`
_RE_RETURN = re.compile(r'^\s*return\s+("(?:[^"\\]|\\.)*")\s*;')

#: 单行 if：`if (cond) return "TOKEN";`
_RE_LINE_IF = re.compile(r'^\s*if\s*\((.*)\)\s*return\s+("(?:[^"\\]|\\.)*")\s*;')

#: 条件里的测试：`/re/.test(host)` / `/re/i.test(url)`（捕获 flags）
_RE_TEST = re.compile(r'/((?:\\.|[^/\\])+)/([a-z]*)\.test\(\s*(host|url)\s*\)')

#: 条件里的 isInNet：`isInNet(host, "1.2.3.0", "255.255.255.0")`
_RE_IS_IN_NET = re.compile(r'isInNet\(\s*host\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')

#: 判定「这个 profile 只是本机直连保护 + 一个出口」的规则数上限
_SIMPLE_PROFILE_MAX_RULES = 8


@dataclass
class PacsOmegaProfile:
    name: str
    rules: list[tuple[str, str, str]] = field(default_factory=list)  # (host/url, pattern, token)
    fallback: str = ""
    nested_init: str = ""
    raw_lines: int = 0


@dataclass
class PacsOmegaImportResult:
    document: PacsDocument = field(default_factory=PacsDocument)
    entry: str = ""
    profile_count: int = 0
    rule_count: int = 0
    deduped_count: int = 0
    direct_count: int = 0
    proxy_count: int = 0
    url_regex_count: int = 0
    host_regex_count: int = 0
    wildcard_count: int = 0
    folded_profiles: list[str] = field(default_factory=list)
    nested_profiles: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def pacs_summary_lines(self) -> list[str]:
        return [
            f"入口配置：{self.entry}",
            f"配置文件数：{self.profile_count} 个 profile",
            f"展开规则：{self.rule_count} 条（去重前 {self.rule_count + self.deduped_count} 条）",
            f"其中直连 {self.direct_count} 条、走代理 {self.proxy_count} 条",
            f"域名后缀规则 {self.rule_count - self.url_regex_count - self.host_regex_count - self.wildcard_count} 条"
            f"，通配域名 {self.wildcard_count} 条"
            f"，主机名正则 {self.host_regex_count} 条"
            f"，URL 正则 {self.url_regex_count} 条",
            f"折叠的出口配置：{('、'.join(self.folded_profiles)) or '无'}",
            f"嵌套的规则列表：{('、'.join(self.nested_profiles)) or '无'}",
            f"无法转换：{len(self.unsupported)} 条",
            f"耗时：{self.elapsed_ms:.0f} ms",
        ]


# --------------------------------------------------------------------------------------
# 对外入口
# --------------------------------------------------------------------------------------
def pacs_import_omega(
    pms_text: str,
    pms_default_proxy: str = "",
    pms_progress: PacsProgress = None,
) -> PacsOmegaImportResult:
    started = time.perf_counter()
    importer = _PacsOmegaImporter(pms_text, pms_progress)
    result = importer.parse()
    result.elapsed_ms = (time.perf_counter() - started) * 1000.0
    if pms_default_proxy and not result.document.default_proxy:
        result.document.default_proxy = pms_default_proxy
    _notify(pms_progress, 100, f"导入完成：{result.rule_count} 条规则，耗时 {result.elapsed_ms:.0f} ms")
    return result


class _PacsOmegaImporter:
    def __init__(self, pms_text: str, pms_progress: PacsProgress = None) -> None:
        self.pacs_text = str(pms_text or "")
        self.pacs_progress = pms_progress
        self.pacs_profiles: dict[str, PacsOmegaProfile] = {}
        self.pacs_result = PacsOmegaImportResult()
        self.pacs_cache: dict[str, tuple[list[PacsRule], str]] = {}

    # ------------------------------------------------------------------ 主流程
    def parse(self) -> PacsOmegaImportResult:
        if "FindProxyForURL" not in self.pacs_text:
            self.pacs_result.warnings.append("文件里没有 FindProxyForURL，可能不是 PAC 脚本")
            return self.pacs_result

        _notify(self.pacs_progress, 5, "扫描 ZeroOmega 配置文件…")
        self._scan_profiles()
        self.pacs_result.profile_count = len(self.pacs_profiles)
        if not self.pacs_profiles:
            self.pacs_result.warnings.append("没找到任何 `\"名字\": function(...)` 形式的配置文件")
            return self.pacs_result

        entry = self._find_entry()
        self.pacs_result.entry = entry
        if not entry:
            self.pacs_result.warnings.append("没找到入口配置（形如 `}（\"入口\", {`）")
            return self.pacs_result
        if entry not in self.pacs_profiles:
            self.pacs_result.warnings.append(f"入口配置「{entry}」在文件里没有定义")

        _notify(self.pacs_progress, 30, f"展开入口配置「{entry}」…")
        rules, default_token = self._expand(entry, [])
        self.pacs_result.document = self._build_document(entry, rules, default_token)
        return self.pacs_result

    # ------------------------------------------------------------------ 扫描
    def _scan_profiles(self) -> None:
        matches = list(_RE_PROFILE_DEF.finditer(self.pacs_text))
        total = max(1, len(matches))
        for index, match in enumerate(matches, start=1):
            name = pacs_js_unescape(match.group(1))
            body, _end = _slice_brace(self.pacs_text, match.end() - 1)
            profile = self._parse_profile_body(name, body)
            # 同名时保留**先出现**的定义（外层优先，与 JS 对象字面量后值覆盖前的语义相反，
            # 但 PAC 里同名 profile 极罕见；保留先出现可避免嵌套壳覆盖真身）
            self.pacs_profiles.setdefault(name, profile)
            if index % 50 == 0:
                _notify(self.pacs_progress, 5 + int(20 * index / total), f"扫描配置 {index}/{total}")

    def _parse_profile_body(self, pms_name: str, pms_body: str) -> PacsOmegaProfile:
        profile = PacsOmegaProfile(name=pms_name)
        profile.raw_lines = pms_body.count("\n") + 1
        outer_body, nested_init, nested_span = self._strip_nested_pac(pms_body)
        profile.nested_init = nested_init
        if nested_init:
            self.pacs_result.nested_profiles.append(nested_init)

        for line in outer_body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = _RE_LINE_IF.match(stripped)
            if match:
                condition = match.group(1).strip()
                token = pacs_js_unescape(_js_decode(match.group(2)))
                if not token:
                    continue
                tests = _RE_TEST.findall(condition)

                # 1) isInNet 条件（本程序导出 IP 段时用的写法）
                net_matches = _RE_IS_IN_NET.findall(condition)
                if net_matches and not tests:
                    residual = _RE_IS_IN_NET.sub("", condition).replace("||", "").strip()
                    if residual:
                        self.pacs_result.unsupported.append(f"{pms_name}：isInNet 与其它条件混用 → {stripped[:120]}")
                        continue
                    for ip, mask in net_matches:
                        profile.rules.append(("ip", f"{ip}/{mask}", token))
                    continue

                if not tests:
                    self.pacs_result.unsupported.append(f"{pms_name}：条件不是 host/url 正则 → {stripped[:120]}")
                    continue

                # 2) `&&` 组合无法安全拆条；纯 `||` 组合则可以拆成多条同动作规则（OR 语义等价）
                if "&&" in condition:
                    self.pacs_result.unsupported.append(f"{pms_name}：多条件与（&&）组合 → {stripped[:120]}")
                    continue
                residual = _RE_TEST.sub("", condition).replace("||", "").strip()
                if residual:
                    self.pacs_result.unsupported.append(f"{pms_name}：含非 host/url 正则的条件 → {stripped[:120]}")
                    continue

                for pattern, flags, target in tests:
                    if flags and "i" in flags and not re.search(r"[\[\](){}|?*+^$\\]", pattern):
                        # 大小写不敏感且不含正则元字符 → 还原成「关键词」规则
                        profile.rules.append(("keyword", pattern, token))
                    else:
                        profile.rules.append(("url" if target == "url" else "host", pattern, token))
                continue
            match = _RE_RETURN.match(stripped)
            if match:
                token = pacs_js_unescape(_js_decode(match.group(1)))
                if token == "FindProxyForURL" or not token:
                    continue
                profile.fallback = token
        del nested_span
        return profile

    def _strip_nested_pac(self, pms_body: str) -> tuple[str, str, tuple[int, int]]:
        """把 profile 体里嵌套的整套 PAC 剥离，返回 (外层文本, 嵌套入口名, 嵌套区间)。"""
        match = _RE_NESTED_ENTRY.search(pms_body)
        if not match:
            return pms_body, "", (-1, -1)
        nested_init = pacs_js_unescape(match.group(1))
        # 嵌套 profiles 对象：从 `{` 开始匹配到对应 `}`
        brace_index = match.end() - 1
        _inner, end_index = _slice_brace(pms_body, brace_index)
        # 覆盖到 `});` / `/* End of PAC */;` / `return FindProxyForURL;` 之后再接回
        tail = pms_body[end_index + 1 :]
        tail = re.sub(r"^\s*\}\s*\)\s*;\s*", "", tail)
        tail = re.sub(r"^\s*/\*\s*End of PAC\s*\*/\s*;\s*", "", tail)
        tail = re.sub(r"^\s*return\s+FindProxyForURL\s*;\s*", "", tail)
        return pms_body[: match.start()] + tail, nested_init, (match.start(), end_index)

    def _find_entry(self) -> str:
        match = _RE_NESTED_ENTRY.search(self.pacs_text)
        return pacs_js_unescape(match.group(1)) if match else ""

    # ------------------------------------------------------------------ 展开
    def _expand(self, pms_name: str, pms_stack: list[str]) -> tuple[list[PacsRule], str]:
        """展开一个 profile → (规则列表, 兜底返回串)。带环检测与缓存。"""
        if pms_name in self.pacs_cache:
            rules, token = self.pacs_cache[pms_name]
            return [rule.pacs_clone() for rule in rules], token
        if pms_name in pms_stack:
            self.pacs_result.warnings.append(f"检测到跳转环：{' → '.join(pms_stack + [pms_name])}")
            return [], ""
        profile = self.pacs_profiles.get(pms_name)
        if profile is None:
            self.pacs_result.warnings.append(f"跳转目标「{pms_name}」不存在")
            return [], ""

        stack = pms_stack + [pms_name]
        out: list[PacsRule] = []

        # 情形 A：这个 profile 只是另一个 PAC 的壳（如 +__ruleListOf_xxx）
        if profile.nested_init:
            inner_rules, inner_token = self._expand(profile.nested_init, stack)
            out.extend(inner_rules)
            if profile.fallback and not profile.fallback.startswith("+"):
                inner_token = profile.fallback
            self.pacs_cache[pms_name] = (out, inner_token)
            return [rule.pacs_clone() for rule in out], inner_token

        # 情形 B：普通规则型 profile
        for kind, pattern, token in profile.rules:
            if token.startswith("+"):
                target = token  # 保留 '+'：profiles 的键本身就带 '+'
                folded, folded_token = self._resolve_jump(target, stack)
                if folded and folded_token:
                    out.append(_rule_from_token(kind, pattern, folded_token))
                    if target not in self.pacs_result.folded_profiles:
                        self.pacs_result.folded_profiles.append(target)
                    continue
                sub_rules, sub_token = self._expand(target, stack)
                if sub_rules:
                    out.extend(sub_rules)
                    self.pacs_result.warnings.append(f"已内联「{target}」的 {len(sub_rules)} 条规则")
                if sub_token:
                    out.append(_all_rule(sub_token, f"内联 {target} 的兜底"))
                    self.pacs_result.warnings.append(
                        f"「{target}」的兜底 {sub_token} 在引用处终止了后续判断（与 ZeroOmega 语义一致）"
                    )
                continue
            out.append(_rule_from_token(kind, pattern, token))

        # 兜底
        fallback = profile.fallback
        if fallback.startswith("+"):
            sub_rules, sub_token = self._expand(fallback, stack)
            out.extend(sub_rules)
            fallback = sub_token
        elif fallback:
            pass
        else:
            fallback = ""

        self.pacs_cache[pms_name] = (out, fallback)
        return [rule.pacs_clone() for rule in out], fallback

    def _resolve_jump(self, pms_target: str, pms_stack: list[str]) -> tuple[bool, str]:
        """判断跳转目标能否折叠成一个固定出口（如 +Master / +I2P）。

        返回 (是否可折叠, 出口 token)。可折叠的条件：
            - 目标存在、不在当前栈里（无环）；
            - 不是嵌套壳（那是规则列表，必须内联）；
            - 规则数很少（只是本机直连保护之类），且有具体的兜底 token。
        折叠后本机保护由生成脚本的头部统一覆盖（脚本开头本来就对
        localhost / 127.0.0.1 / ::1 / 纯主机名一律直连）。
        """
        target = self.pacs_profiles.get(pms_target)
        if target is None or pms_target in pms_stack:
            return False, ""
        if target.nested_init:
            return False, ""
        if len(target.rules) > _SIMPLE_PROFILE_MAX_RULES:
            return False, ""
        if not target.fallback or target.fallback.startswith("+"):
            return False, ""
        return True, target.fallback

    # ------------------------------------------------------------------ 文档
    def _build_document(
        self,
        pms_entry: str,
        pms_rules: list[PacsRule],
        pms_default_token: str,
    ) -> PacsDocument:
        _notify(self.pacs_progress, 80, "整理规则（去重 / 归类）…")
        doc = PacsDocument(name="从 ZeroOmega 导入", default_action="direct")
        seen: set[tuple[str, str, str, str]] = set()
        unique: list[PacsRule] = []
        for rule in pms_rules:
            key = (rule.match, rule.content.lower(), rule.action, rule.proxy)
            if key in seen:
                self.pacs_result.deduped_count += 1
                continue
            seen.add(key)
            unique.append(rule)

        for rule in unique:
            if rule.action == PACS_ACTION_DIRECT:
                self.pacs_result.direct_count += 1
            else:
                self.pacs_result.proxy_count += 1
            if rule.match == PACS_MATCH_URL_REGEX:
                self.pacs_result.url_regex_count += 1
            elif rule.match == PACS_MATCH_HOST_REGEX:
                self.pacs_result.host_regex_count += 1
            elif rule.match == PACS_MATCH_DOMAIN_WILDCARD:
                self.pacs_result.wildcard_count += 1

        doc.rules = unique
        self.pacs_result.rule_count = len(unique)

        action, addr, fallback_direct = pacs_split_token(pms_default_token) if pms_default_token else (
            PACS_ACTION_DIRECT, "", False
        )
        if action == PACS_ACTION_DIRECT or not pms_default_token:
            doc.default_action = "direct"
        else:
            doc.default_action = "proxy"
            doc.default_proxy = addr
            doc.default_scheme = action
            doc.mixed_add_direct_fallback = fallback_direct
        if not doc.default_proxy:
            # 兜底：从代理规则里取一个地址，避免「默认走代理但没地址」
            for rule in unique:
                if rule.action != PACS_ACTION_DIRECT and rule.proxy:
                    doc.default_proxy = rule.proxy
                    doc.default_scheme = rule.action
                    doc.default_action = "direct"  # 保守：默认仍直连
                    break
        return doc


# --------------------------------------------------------------------------------------
# 规则构造
# --------------------------------------------------------------------------------------
def _rule_from_token(pms_kind: str, pms_pattern: str, pms_token: str) -> PacsRule:
    action, addr, fallback = pacs_split_token(pms_token)
    pattern = _unescape_regex(pms_pattern)
    match = PACS_MATCH_HOST_REGEX
    content = pattern
    if pms_kind == "url":
        match = PACS_MATCH_URL_REGEX
    elif pms_kind == "keyword":
        match = PACS_MATCH_KEYWORD
        content = pattern
    elif pms_kind == "ip":
        ip, _, mask = pattern.partition("/")
        match = PACS_MATCH_IP_CIDR
        content = f"{ip}/{pacs_mask_to_cidr(mask)}"
    else:
        suffix = _regex_to_domain_suffix(pattern)
        if suffix:
            match = PACS_MATCH_DOMAIN_SUFFIX
            content = suffix
        else:
            wildcard = _regex_to_wildcard(pattern)
            if wildcard:
                match = PACS_MATCH_DOMAIN_WILDCARD
                content = wildcard
    return PacsRule(
        match=match,
        content=content,
        action=action,
        proxy=addr if action != PACS_ACTION_DIRECT else "",
        fallback_direct=fallback,
        note="",
        enabled=True,
    )


def _all_rule(pms_token: str, pms_note: str) -> PacsRule:
    action, addr, fallback = pacs_split_token(pms_token)
    return PacsRule(
        match=PACS_MATCH_ALL,
        content="",
        action=action,
        proxy=addr if action != PACS_ACTION_DIRECT else "",
        fallback_direct=fallback,
        note=pms_note,
        enabled=True,
    )


# --------------------------------------------------------------------------------------
# 正则归一
# --------------------------------------------------------------------------------------
def _regex_to_domain_suffix(pms_pattern: str) -> str:
    """`(?:^|\\.)example\\.com$` → example.com（只认无其它元字符的纯域名）。

    注意：判断前必须把 `\\.` 这类转义还原，否则会把「合法的点」误判成元字符，
    导致几千条域名规则退化成主机名正则（可编辑性大幅下降）。
    """
    text = str(pms_pattern or "").strip()
    match = re.fullmatch(r"\(\?:\^\|\\\.\)(.+)\$", text)
    if not match:
        match = re.fullmatch(r"\^?\\\.(.+)\$", text)
    if not match:
        match = re.fullmatch(r"\^([A-Za-z0-9_.\-]+)\$", text)
    if not match:
        return ""
    plain = _regex_unescape(match.group(1))
    if re.search(r"[\[\](){}|?*+^$\\]", plain):
        return ""
    return pacs_normalize_domain(plain)


def _regex_to_wildcard(pms_pattern: str) -> str:
    """`(?:^|\\.).*\\.tokenplus\\.app$` → `*.tokenplus.app`（含本程序导出器的写法）。

    额外支持域名中间带通配的形式，例如
        `(?:^|\\.)cdn.*\\.i-scmp\\.com$` → `cdn*.i-scmp.com`
    （`(?:^|\\.)` 前缀保证是按域名边界匹配，因此 `.*` 可以安全地映射成通配 `*`）。
    """
    text = str(pms_pattern or "").strip()
    patterns = (
        r"\(\?:\^\|\\\.\)\.\*\\\.(.+)\$",
        r"\(\?:\^\|\\\.\)\(\?:\.\*\\\.\)\?(.+)\$",
    )
    for raw in patterns:
        match = re.fullmatch(raw, text)
        if not match:
            continue
        plain = _regex_unescape(match.group(1))
        if re.search(r"[\[\](){}|?+^$\\/:]", plain):
            return ""
        return "*." + pacs_normalize_domain(plain)

    # 域名中间通配：`(?:^|\.)cdn.*\.i-scmp\.com$`
    match = re.fullmatch(r"\(\?:\^\|\\\.\)(.+)\$", text)
    if match:
        inner = match.group(1)
        placeholder = "\x00"
        guarded = inner.replace(".*", placeholder)
        plain = _regex_unescape(guarded)
        if re.search(r"[\[\](){}|?+^$\\/:*]", plain.replace(placeholder, "")):
            return ""
        if placeholder not in plain:
            return ""
        return plain.replace(placeholder, "*").lower()
    return ""


def _regex_unescape(pms_text: str) -> str:
    """把正则里的 `\\.` / `\\-` 之类还原成字符（只用于「能否当纯域名」的判断）。"""
    return re.sub(r"\\(.)", r"\1", str(pms_text or ""))


def _unescape_regex(pms_pattern: str) -> str:
    return str(pms_pattern or "").replace("\\/", "/")


def _js_decode(pms_literal: str) -> str:
    text = str(pms_literal or "").strip()
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return pacs_js_unescape(text[1:-1])
    return pacs_js_unescape(text)


# --------------------------------------------------------------------------------------
# JS 扫描（跳过字符串 / 正则字面量 / 注释，否则正则里的 { } 会打乱花括号配对）
# --------------------------------------------------------------------------------------
def _slice_brace(pms_text: str, pms_open_index: int) -> tuple[str, int]:
    if pms_open_index >= len(pms_text) or pms_text[pms_open_index] != "{":
        return "", pms_open_index
    depth = 0
    index = pms_open_index
    length = len(pms_text)
    prev_significant = ""
    while index < length:
        char = pms_text[index]
        if char in ('"', "'"):
            index = _skip_string(pms_text, index)
            prev_significant = '"'
            continue
        if char == "/" and index + 1 < length and pms_text[index + 1] == "/":
            newline = pms_text.find("\n", index)
            index = length if newline < 0 else newline
            continue
        if char == "/" and index + 1 < length and pms_text[index + 1] == "*":
            end = pms_text.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue
        if char == "/" and _regex_allowed(prev_significant):
            index = _skip_regex(pms_text, index)
            prev_significant = "/"
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pms_text[pms_open_index + 1 : index], index
        if not char.isspace():
            prev_significant = char
        index += 1
    return pms_text[pms_open_index + 1 :], length


def _regex_allowed(pms_prev: str) -> bool:
    """启发式判断 `/` 是正则起点还是除号。PAC 里几乎不出现除号。"""
    if not pms_prev:
        return True
    return pms_prev in "(,=:[!&|?{};+-*%<>~^"


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


def _skip_regex(pms_text: str, pms_index: int) -> int:
    index = pms_index + 1
    length = len(pms_text)
    in_class = False
    while index < length:
        char = pms_text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            index += 1
            while index < length and pms_text[index].isalpha():
                index += 1
            return index
        elif char == "\n":
            return index
        index += 1
    return length


def _notify(pms_progress: PacsProgress, pms_percent: int, pms_message: str) -> None:
    if pms_progress is None:
        return
    try:
        pms_progress(max(0, min(100, int(pms_percent))), pms_message)
    except Exception:  # noqa: BLE001
        pass
