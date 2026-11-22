# -*- coding: utf-8 -*-
"""内置模板与常用直连清单（开箱即用的起点）。"""

from __future__ import annotations

from typing import Optional

from pacs.constants import (
    PACS_ACTION_DIRECT,
    PACS_ACTION_MIXED,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_DEFAULT_PROXY_ADDRESS,
    PACS_DEFAULT_PROXY_SCHEME,
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_KEYWORD,
)
from pacs.pac.model import PacsDocument, PacsRule

#: 常见国内站点（「国内直连、其余走代理」模板用）。只是起点，用户可随意增删。
PACS_BUILTIN_CN_DIRECT_DOMAINS = [
    "cn",
    "baidu.com",
    "qq.com",
    "taobao.com",
    "tmall.com",
    "alipay.com",
    "jd.com",
    "bilibili.com",
    "163.com",
    "126.com",
    "aliyun.com",
    "alicdn.com",
    "tencent.com",
    "weixin.qq.com",
    "bytedance.com",
    "douyin.com",
    "mi.com",
    "huawei.com",
    "csdn.net",
    "zhihu.com",
    "sohu.com",
    "sina.com.cn",
    "sinaimg.cn",
    "iqiyi.com",
    "youku.com",
    "meituan.com",
    "dianping.com",
    "pinduoduo.com",
    "xiaohongshu.com",
    "kuaishou.com",
]

#: 模板结构：(名称, 说明, 默认动作, 默认协议, [(匹配类型, 内容, 动作, 备注)])
PACS_BUILTIN_TEMPLATES: list[tuple[str, str, str, str, list[tuple[str, str, str, str]]]] = [
    (
        "国内直连，其余走代理",
        "最常用：常见国内站点直连，其它全部走外部代理。",
        "proxy",
        PACS_ACTION_SOCKS5,
        [(PACS_MATCH_DOMAIN_SUFFIX, domain, PACS_ACTION_DIRECT, "国内站点直连") for domain in PACS_BUILTIN_CN_DIRECT_DOMAINS],
    ),
    (
        "只有指定站点走代理",
        "其余全部直连，只有你列的站点走代理。适合偶尔访问特定站点。",
        "direct",
        PACS_ACTION_SOCKS5,
        [
            (PACS_MATCH_DOMAIN_SUFFIX, "google.com", PACS_ACTION_SOCKS5, "示例：谷歌"),
            (PACS_MATCH_DOMAIN_SUFFIX, "youtube.com", PACS_ACTION_SOCKS5, "示例：油管"),
            (PACS_MATCH_DOMAIN_SUFFIX, "telegram.org", PACS_ACTION_SOCKS5, "示例：电报"),
        ],
    ),
    (
        "全部流量走代理",
        "最简单：所有网站都走外部代理，不做任何直连判断。",
        "proxy",
        PACS_ACTION_SOCKS5,
        [],
    ),
    (
        "全部直连（等于不代理）",
        "所有网站都直连。用于临时关掉分流、又不改系统代理设置。",
        "direct",
        PACS_ACTION_DIRECT,
        [],
    ),
]

#: 内置「内网 / 本机」直连判断（编译时自动加到脚本头部，不可通过规则删除）
PACS_BUILTIN_LOCAL_BYPASS_NOTE = (
    "localhost / 127.0.0.1 / ::1 / 纯主机名（内网机器名）一律直连，"
    "避免访问本机服务时绕进代理。"
)


def pacs_new_document(
    pms_name: str = "默认方案",
    pms_default_proxy: str = PACS_DEFAULT_PROXY_ADDRESS,
    pms_default_scheme: str = PACS_DEFAULT_PROXY_SCHEME,
) -> PacsDocument:
    """新建一份空方案（默认动作=走代理，指向默认外部代理）。"""
    scheme = pms_default_scheme if pms_default_scheme in (
        PACS_ACTION_PROXY, PACS_ACTION_SOCKS5, PACS_ACTION_MIXED
    ) else PACS_ACTION_SOCKS5
    return PacsDocument(
        name=pms_name,
        default_action="proxy",
        default_proxy=pms_default_proxy or PACS_DEFAULT_PROXY_ADDRESS,
        default_scheme=scheme,
        rules=[],
    )


def pacs_document_from_template(
    pms_index: int,
    pms_default_proxy: str = PACS_DEFAULT_PROXY_ADDRESS,
    pms_name: str = "",
) -> Optional[PacsDocument]:
    """按模板序号（1 起）造一份方案；序号越界返回 None。"""
    if pms_index < 1 or pms_index > len(PACS_BUILTIN_TEMPLATES):
        return None
    name, _desc, default_action, scheme, rows = PACS_BUILTIN_TEMPLATES[pms_index - 1]
    rules: list[PacsRule] = []
    for match, content, action, note in rows:
        rules.append(
            PacsRule(match=match, content=content, action=action, proxy="", note=note)
        )
    # 模板自带的「示例」规则若与默认动作冲突，保留原样；用户可再改
    return PacsDocument(
        name=pms_name or name,
        default_action=default_action,
        default_proxy=pms_default_proxy or PACS_DEFAULT_PROXY_ADDRESS,
        default_scheme=scheme,
        rules=rules,
    )


def pacs_template_names() -> list[str]:
    return [item[0] for item in PACS_BUILTIN_TEMPLATES]


def pacs_template_desc(pms_index: int) -> str:
    if 1 <= pms_index <= len(PACS_BUILTIN_TEMPLATES):
        return PACS_BUILTIN_TEMPLATES[pms_index - 1][1]
    return ""


#: 示例规则（首次打开空方案时给一条，避免空白表让人不知所措）
PACS_SAMPLE_RULES: list[PacsRule] = [
    PacsRule(
        match=PACS_MATCH_DOMAIN_SUFFIX,
        content="baidu.com",
        action=PACS_ACTION_DIRECT,
        note="示例：百度直连（可删）",
    ),
    PacsRule(
        match=PACS_MATCH_KEYWORD,
        content="google",
        action=PACS_ACTION_SOCKS5,
        note="示例：域名含 google 走代理（可删）",
    ),
]
