# -*- coding: utf-8 -*-
"""PAC 数据模型：单条规则 + 一份分流方案（文档）。

**真源纪律**：规则的唯一真源是 `data/profiles/<方案>.json`，不是 PAC 脚本文件。
PAC 脚本是编译产物；「专业模式」里手改脚本后回解析只是尽力而为的便利功能，
解析不出来时规则表保持不变（不会被清空），避免用户误操作丢规则。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_ACTIONS,
    PACS_DEFAULT_PROXY_ADDRESS,
    PACS_DEFAULT_PROXY_SCHEME,
    PACS_MATCH_ALL,
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_DOMAIN_WILDCARD,
    PACS_MATCH_HOST_REGEX,
    PACS_MATCH_IP_CIDR,
    PACS_MATCH_KEYWORD,
    PACS_MATCH_LABELS,
    PACS_MATCH_TYPES,
    PACS_MATCH_URL_REGEX,
)
from pacs.utils import (
    pacs_cidr_to_mask,
    pacs_is_valid_proxy_address,
    pacs_mask_to_cidr,
    pacs_normalize_domain,
    pacs_now_text,
    pacs_safe_int,
    pacs_split_proxy,
)


# --------------------------------------------------------------------------------------
# 单条规则
# --------------------------------------------------------------------------------------
@dataclass
class PacsRule:
    """一条分流规则。

    匹配语义（从上到下，先命中先生效）：
        domain_suffix   域名后缀：`baidu.com` 命中 baidu.com 及所有子域（等价 `*.baidu.com`）
        domain_wildcard 通配域名：`*.google.com` / `*.google.co.*`（`*` 匹配任意字符，含点）
        keyword         关键词：host 或完整 url 里包含该字符串
        url_regex       URL 正则：对完整 url 做正则测试
        host_regex      主机名正则：对 host 做正则测试（ZeroOmega 导入的兜底类型）
        ip_cidr         IP 段：`***已脱敏***-内网IP/16` 或裸 IP
        all             全部流量：无条件命中（其后规则不可达）
    """

    match: str = PACS_MATCH_DOMAIN_SUFFIX
    content: str = ""
    action: str = PACS_ACTION_DIRECT
    proxy: str = ""
    fallback_direct: bool = False
    note: str = ""
    enabled: bool = True

    # ------------------------------------------------------------------ 序列化
    def pacs_to_dict(self) -> dict[str, Any]:
        return {
            "match": self.match,
            "content": self.content,
            "action": self.action,
            "proxy": self.proxy,
            "fallback_direct": bool(self.fallback_direct),
            "note": self.note,
            "enabled": bool(self.enabled),
        }

    @classmethod
    def pacs_from_dict(cls, pms_raw: dict[str, Any]) -> "PacsRule":
        raw = pms_raw if isinstance(pms_raw, dict) else {}
        match = str(raw.get("match", PACS_MATCH_DOMAIN_SUFFIX))
        if match not in PACS_MATCH_TYPES:
            match = PACS_MATCH_DOMAIN_SUFFIX
        action = str(raw.get("action", PACS_ACTION_DIRECT)).upper()
        if action not in PACS_ACTIONS:
            action = PACS_ACTION_DIRECT
        return cls(
            match=match,
            content=str(raw.get("content", "") or "").strip(),
            action=action,
            proxy=str(raw.get("proxy", "") or "").strip(),
            fallback_direct=bool(raw.get("fallback_direct", False)),
            note=str(raw.get("note", "") or ""),
            enabled=bool(raw.get("enabled", True)),
        )

    # ------------------------------------------------------------------ 归一化
    def pacs_normalized_content(self) -> str:
        """按匹配类型归一匹配内容（域名去 `*.`、IP 段统一成 a.b.c.d/n）。"""
        text = str(self.content or "").strip()
        if self.match in (PACS_MATCH_DOMAIN_SUFFIX, PACS_MATCH_DOMAIN_WILDCARD):
            if self.match == PACS_MATCH_DOMAIN_WILDCARD and text.startswith("*"):
                # 通配保留 * 语义，只规整前后多余符号
                return text.lower().lstrip(".").rstrip(".")
            return pacs_normalize_domain(text)
        if self.match == PACS_MATCH_IP_CIDR:
            return self.pacs_ip_cidr_normalized()
        return text

    def pacs_ip_cidr_normalized(self) -> str:
        text = str(self.content or "").strip()
        if "/" in text:
            return text
        return text

    def pacs_ip_parts(self) -> tuple[str, str]:
        """IP 段规则 → (网络地址, 掩码)；非法时返回 ("", "")。"""
        text = str(self.content or "").strip()
        if not text:
            return "", ""
        if "/" in text:
            ip, _, bits = text.partition("/")
            return ip.strip(), pacs_cidr_to_mask(bits.strip())
        return text, "255.255.255.255"

    def pacs_ip_bits(self) -> str:
        """IP 段 → 位数文本（用于界面展示 `***已脱敏***-内网IP/16`）。"""
        text = str(self.content or "").strip()
        if "/" in text:
            ip, _, bits = text.partition("/")
            return f"{ip.strip()}/{bits.strip()}"
        return f"{text}/32"

    # ------------------------------------------------------------------ 校验
    def pacs_validate(self, pms_default_proxy: str = "") -> tuple[bool, str]:
        """返回 (是否合法, 中文原因)。用于保存前逐条体检。"""
        if not self.enabled:
            return True, "已停用"
        if self.match not in PACS_MATCH_TYPES:
            return False, f"未知的匹配类型：{self.match}"
        if self.match != PACS_MATCH_ALL and not str(self.content or "").strip():
            return False, f"「{PACS_MATCH_LABELS.get(self.match, self.match)}」规则没填匹配内容"
        if self.match == PACS_MATCH_URL_REGEX:
            ok, reason = _pacs_check_regex(self.content)
            if not ok:
                return False, f"URL 正则写错了：{reason}"
        if self.match == PACS_MATCH_HOST_REGEX:
            ok, reason = _pacs_check_regex(self.content)
            if not ok:
                return False, f"主机名正则写错了：{reason}"
        if self.match == PACS_MATCH_IP_CIDR:
            ip, mask = self.pacs_ip_parts()
            if not _pacs_is_ipv4(ip):
                return False, f"IP 段「{self.content}」的地址部分不是合法的 IPv4"
        if self.action in (PACS_ACTION_PROXY, PACS_ACTION_SOCKS5, PACS_ACTION_MIXED):
            addr = str(self.proxy or "").strip() or str(pms_default_proxy or "").strip()
            if not addr:
                return False, "走代理的规则既没填代理地址，方案里也没有默认代理地址"
            if not pacs_is_valid_proxy_address(addr):
                return False, f"代理地址「{addr}」格式不对，应为 IP:端口（例如 ***已脱敏***-内网IP:20808）"
        return True, ""

    # ------------------------------------------------------------------ 展示
    def pacs_action_text(self, pms_default_proxy: str = "", pms_default_scheme: str = "") -> str:
        if self.action == PACS_ACTION_DIRECT:
            return "直连"
        addr = self.proxy or pms_default_proxy
        scheme = {
            PACS_ACTION_PROXY: "PROXY",
            PACS_ACTION_SOCKS5: "SOCKS5",
            PACS_ACTION_MIXED: "混合",
        }.get(self.action, pms_default_scheme or "代理")
        return f"{scheme} → {addr or '（未填地址）'}"

    def pacs_summary(self, pms_default_proxy: str = "", pms_default_scheme: str = "") -> str:
        match_text = {
            PACS_MATCH_DOMAIN_SUFFIX: "域名以 {c} 结尾",
            PACS_MATCH_DOMAIN_WILDCARD: "域名匹配 {c}",
            PACS_MATCH_KEYWORD: "网址或域名含 {c}",
            PACS_MATCH_URL_REGEX: "URL 匹配正则 {c}",
            PACS_MATCH_HOST_REGEX: "主机名匹配正则 {c}",
            PACS_MATCH_IP_CIDR: "目标 IP 在 {c} 内",
            PACS_MATCH_ALL: "所有流量",
        }.get(self.match, "匹配 {c}").format(c=self.content or "（空）")
        return f"{match_text} → {self.pacs_action_text(pms_default_proxy, pms_default_scheme)}"

    def pacs_clone(self) -> "PacsRule":
        return PacsRule(**self.pacs_to_dict())


def _pacs_check_regex(pms_pattern: str) -> tuple[bool, str]:
    """尽力校验正则（JS 与 Python 语法不完全一致，这里只拦明显写错的）。"""
    text = str(pms_pattern or "")
    if not text:
        return False, "内容为空"
    try:
        re.compile(text)
        return True, ""
    except re.error as exc:
        return False, str(exc)


def _pacs_is_ipv4(pms_text: str) -> bool:
    parts = str(pms_text or "").strip().split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        if not 0 <= int(part) <= 255:
            return False
    return True


# --------------------------------------------------------------------------------------
# 一份分流方案
# --------------------------------------------------------------------------------------
@dataclass
class PacsDocument:
    """一份完整分流方案 = 默认动作 + 默认代理 + 有序规则表。"""

    name: str = "默认方案"
    default_action: str = "proxy"                  # proxy / direct
    default_proxy: str = PACS_DEFAULT_PROXY_ADDRESS
    default_scheme: str = PACS_DEFAULT_PROXY_SCHEME  # PROXY / SOCKS5 / MIXED
    mixed_add_direct_fallback: bool = False
    rules: list[PacsRule] = field(default_factory=list)
    updated_at: str = ""

    # ------------------------------------------------------------------ 序列化
    def pacs_to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "default_action": self.default_action,
            "default_proxy": self.default_proxy,
            "default_scheme": self.default_scheme,
            "mixed_add_direct_fallback": bool(self.mixed_add_direct_fallback),
            "updated_at": self.updated_at or pacs_now_text(),
            "rules": [rule.pacs_to_dict() for rule in self.rules],
        }

    @classmethod
    def pacs_from_dict(cls, pms_raw: dict[str, Any], pms_name: str = "") -> "PacsDocument":
        raw = pms_raw if isinstance(pms_raw, dict) else {}
        default_action = str(raw.get("default_action", "proxy")).strip().lower()
        if default_action not in ("proxy", "direct"):
            default_action = "proxy"
        scheme = str(raw.get("default_scheme", PACS_DEFAULT_PROXY_SCHEME)).strip().upper()
        if scheme not in (PACS_ACTION_PROXY, PACS_ACTION_SOCKS5, PACS_ACTION_MIXED):
            scheme = PACS_DEFAULT_PROXY_SCHEME
        rules: list[PacsRule] = []
        for item in raw.get("rules", []) or []:
            try:
                rules.append(PacsRule.pacs_from_dict(item))
            except Exception:  # noqa: BLE001 跳过坏条目，不整份失败
                continue
        return cls(
            name=str(raw.get("name") or pms_name or "默认方案"),
            default_action=default_action,
            default_proxy=str(raw.get("default_proxy") or PACS_DEFAULT_PROXY_ADDRESS).strip(),
            default_scheme=scheme,
            mixed_add_direct_fallback=bool(raw.get("mixed_add_direct_fallback", False)),
            rules=rules,
            updated_at=str(raw.get("updated_at") or ""),
        )

    # ------------------------------------------------------------------ 统计
    def pacs_enabled_rules(self) -> list[PacsRule]:
        return [rule for rule in self.rules if rule.enabled]

    def pacs_stats(self) -> dict[str, int]:
        enabled = self.pacs_enabled_rules()
        by_type: dict[str, int] = {}
        for rule in enabled:
            by_type[rule.match] = by_type.get(rule.match, 0) + 1
        return {
            "total": len(self.rules),
            "enabled": len(enabled),
            "disabled": len(self.rules) - len(enabled),
            "proxy_rules": sum(1 for r in enabled if r.action != PACS_ACTION_DIRECT),
            "direct_rules": sum(1 for r in enabled if r.action == PACS_ACTION_DIRECT),
            **{f"type_{key}": value for key, value in by_type.items()},
        }

    def pacs_validate_all(self) -> list[tuple[int, str]]:
        """逐条体检，返回 [(规则序号, 原因)]（序号从 1 开始，便于对着表格看）。"""
        problems: list[tuple[int, str]] = []
        for index, rule in enumerate(self.rules, start=1):
            ok, reason = rule.pacs_validate(self.default_proxy)
            if not ok:
                problems.append((index, reason))
        if self.default_action == "proxy" and not str(self.default_proxy or "").strip():
            problems.append((0, "默认动作是「走代理」，但方案里没填默认代理地址"))
        return problems

    def pacs_effective_default_token(self) -> str:
        """默认动作 → PAC 返回串（供编译器与界面预览共用）。"""
        if self.default_action != "proxy":
            return PACS_ACTION_DIRECT
        return pacs_build_token(
            PACS_ACTION_MIXED if self.default_scheme == PACS_ACTION_MIXED else self.default_scheme,
            self.default_proxy,
            self.mixed_add_direct_fallback,
        )

    def pacs_clone(self) -> "PacsDocument":
        return PacsDocument.pacs_from_dict(self.pacs_to_dict(), self.name)


# --------------------------------------------------------------------------------------
# 动作 → PAC 返回串
# --------------------------------------------------------------------------------------
def pacs_build_token(
    pms_action: str,
    pms_proxy: str,
    pms_mixed_fallback_direct: bool = False,
) -> str:
    """把动作 + 地址拼成 PAC 的返回串。

    MIXED 的语义：先试 HTTP 代理，再试 SOCKS5（PAC 支持分号分隔的备选列表），
    可选再追加 DIRECT 兜底。注意 Windows 自带 WinINET/IE 对 SOCKS5 支持不完整，
    Chrome / Edge / Firefox 自带 PAC 引擎可以正常按顺序尝试。
    """
    action = str(pms_action or PACS_ACTION_DIRECT).upper()
    addr = str(pms_proxy or "").strip()
    if action == PACS_ACTION_DIRECT:
        return "DIRECT"
    if not addr:
        return "DIRECT"
    if action == PACS_ACTION_PROXY:
        return f"PROXY {addr}"
    if action == PACS_ACTION_SOCKS5:
        return f"SOCKS5 {addr}"
    if action == PACS_ACTION_MIXED:
        parts = [f"PROXY {addr}", f"SOCKS5 {addr}"]
        if pms_mixed_fallback_direct:
            parts.append("DIRECT")
        return "; ".join(parts)
    return "DIRECT"


def pacs_split_token(pms_token: str) -> tuple[str, str, bool]:
    """PAC 返回串 → (动作, 代理地址, 是否带 DIRECT 兜底)。供反解析与 ZeroOmega 导入复用。"""
    text = str(pms_token or "").strip()
    if not text or text.upper() == "DIRECT":
        return PACS_ACTION_DIRECT, "", False
    parts = [part.strip() for part in text.split(";") if part.strip()]
    kinds: list[str] = []
    addrs: list[str] = []
    has_direct = False
    for part in parts:
        upper = part.upper()
        if upper == "DIRECT":
            has_direct = True
            continue
        scheme, _, addr = part.partition(" ")
        scheme = scheme.strip().upper()
        addr = addr.strip()
        if scheme in ("PROXY", "HTTP"):
            kinds.append(PACS_ACTION_PROXY)
            addrs.append(addr)
        elif scheme in ("SOCKS5", "SOCKS"):
            kinds.append(PACS_ACTION_SOCKS5)
            addrs.append(addr)
        else:
            kinds.append("")
            addrs.append(part)
    if len(kinds) == 1 and kinds[0]:
        return kinds[0], addrs[0], has_direct
    if len(set(kinds)) == 1 and kinds and kinds[0]:
        return kinds[0], addrs[0], has_direct
    if PACS_ACTION_PROXY in kinds and PACS_ACTION_SOCKS5 in kinds:
        # 同址才可合成 MIXED；不同址会丢信息，调用方需检查 addrs 是否一致
        if len(set(addrs)) == 1:
            return PACS_ACTION_MIXED, addrs[0], has_direct
        return PACS_ACTION_MIXED, addrs[0], has_direct
    return PACS_ACTION_DIRECT, "", has_direct


def pacs_token_address(pms_token: str) -> str:
    """从返回串里取第一个代理地址（用于界面回填）。"""
    _action, addr, _fallback = pacs_split_token(pms_token)
    return addr


def pacs_host_from_proxy(pms_address: str) -> str:
    host, _port = pacs_split_proxy(pms_address)
    return host


def pacs_normalize_ip_cidr(pms_text: str) -> str:
    """把 `1.2.3.4/24` / `1.2.3.4 255.255.255.0` / 裸 IP 统一成 `a.b.c.d/n`。"""
    text = str(pms_text or "").strip()
    if not text:
        return ""
    if " " in text:
        ip, _, mask = text.partition(" ")
        if _pacs_is_ipv4(mask.strip()):
            return f"{ip.strip()}/{pacs_mask_to_cidr(mask.strip())}"
        return text
    return text


__all__ = [
    "PacsRule",
    "PacsDocument",
    "pacs_build_token",
    "pacs_split_token",
    "pacs_token_address",
    "pacs_normalize_ip_cidr",
    "pacs_safe_int",
    "pacs_now_text",
    "Optional",
]
