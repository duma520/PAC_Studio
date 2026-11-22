# -*- coding: utf-8 -*-
"""PAC 分流工作室（PAC Studio）· 全局常量。

所有「魔法字符串」集中在这里：版本号、目录名、动作关键字、匹配类型、默认外部代理。
新版本发布时**只改本文件的版本号**，其余模块一律引用常量。
"""

from __future__ import annotations

import os

# --------------------------------------------------------------------------------------
# 应用身份
# --------------------------------------------------------------------------------------
PACS_APP_NAME = "PAC 分流工作室"
PACS_APP_NAME_EN = "PAC Studio"
PACS_APP_VERSION = "1.0.5"
PACS_APP_ID = "pac_studio"
PACS_LOGGER_NAME = "pac_studio"
PACS_IS_WINDOWS = os.name == "nt"

# --------------------------------------------------------------------------------------
# 目录与文件名
# --------------------------------------------------------------------------------------
PACS_DIR_DATA = "data"
PACS_DIR_LOGS = "logs"
PACS_DIR_VERSION = "version"
PACS_DIR_SCAFFOLD = "_scaffold"
PACS_DIR_DOCS = "docs"
PACS_DIR_PROFILES = "profiles"

PACS_SETTINGS_FILENAME = "pac_settings.json"
PACS_SETTINGS_BACKUP_FILENAME = "pac_settings.json.bak"
PACS_PAC_FILENAME = "pac_current.pac"
PACS_PROFILE_INDEX_FILENAME = "profiles.json"
PACS_ICON_FILENAME = "icon.ico"
PACS_LOG_FILENAME = "pac_studio.log"
PACS_ITERATION_DOC = "软件升级迭代记录.md"
PACS_MAIN_SCRIPT = "PAC_Studio.py"

# 方案文件名里允许的字符（防目录穿越 / 非法 Windows 文件名）
PACS_PROFILE_NAME_MAX = 40

# --------------------------------------------------------------------------------------
# 默认外部代理（用户指定：***已脱敏***-内网IP:20808，与 OmegaProfile.pac 的 +Master 一致）
# --------------------------------------------------------------------------------------
PACS_DEFAULT_PROXY_ADDRESS = "***已脱敏***-内网IP:20808"
PACS_DEFAULT_PROXY_SCHEME = "SOCKS5"

# --------------------------------------------------------------------------------------
# 动作（规则命中后怎么走）—— 值为 PAC 返回值里的关键字
# --------------------------------------------------------------------------------------
PACS_ACTION_DIRECT = "DIRECT"
PACS_ACTION_PROXY = "PROXY"
PACS_ACTION_SOCKS5 = "SOCKS5"
PACS_ACTION_MIXED = "MIXED"

#: 界面下拉的固定顺序；MIXED = 同时给 PROXY 与 SOCKS5 两条备选，PAC 会依次尝试
PACS_ACTIONS = [
    PACS_ACTION_DIRECT,
    PACS_ACTION_PROXY,
    PACS_ACTION_SOCKS5,
    PACS_ACTION_MIXED,
]

PACS_ACTION_LABELS = {
    PACS_ACTION_DIRECT: "直连 DIRECT",
    PACS_ACTION_PROXY: "HTTP 代理 PROXY",
    PACS_ACTION_SOCKS5: "SOCKS5 代理",
    PACS_ACTION_MIXED: "混合（PROXY→SOCKS5）",
}

PACS_ACTION_LABEL_TO_VALUE = {label: value for value, label in PACS_ACTION_LABELS.items()}

#: 允许用「默认代理地址」的动作（DIRECT 不需要地址）
PACS_ACTIONS_USING_PROXY = [PACS_ACTION_PROXY, PACS_ACTION_SOCKS5, PACS_ACTION_MIXED]

# --------------------------------------------------------------------------------------
# 匹配类型
# --------------------------------------------------------------------------------------
PACS_MATCH_DOMAIN_SUFFIX = "domain_suffix"       # 域名后缀：baidu.com 覆盖 baidu.com 及所有子域
PACS_MATCH_DOMAIN_WILDCARD = "domain_wildcard"   # 通配域名：*.google.com（可含 *，也可写 .google.com）
PACS_MATCH_KEYWORD = "keyword"                   # 关键词：host 或 url 里包含
PACS_MATCH_URL_REGEX = "url_regex"               # URL 正则：对完整 url 做正则测试
PACS_MATCH_HOST_REGEX = "host_regex"             # 主机名正则：对 host 做正则测试
PACS_MATCH_IP_CIDR = "ip_cidr"                   # IP 段：***已脱敏***-内网IP/16
PACS_MATCH_ALL = "all"                           # 全部流量：无条件返回

PACS_MATCH_TYPES = [
    PACS_MATCH_DOMAIN_SUFFIX,
    PACS_MATCH_DOMAIN_WILDCARD,
    PACS_MATCH_KEYWORD,
    PACS_MATCH_URL_REGEX,
    PACS_MATCH_HOST_REGEX,
    PACS_MATCH_IP_CIDR,
    PACS_MATCH_ALL,
]

PACS_MATCH_LABELS = {
    PACS_MATCH_DOMAIN_SUFFIX: "域名后缀",
    PACS_MATCH_DOMAIN_WILDCARD: "通配域名",
    PACS_MATCH_KEYWORD: "关键词",
    PACS_MATCH_URL_REGEX: "URL 正则",
    PACS_MATCH_HOST_REGEX: "主机名正则",
    PACS_MATCH_IP_CIDR: "IP 段",
    PACS_MATCH_ALL: "全部流量",
}

PACS_MATCH_LABEL_TO_VALUE = {label: value for value, label in PACS_MATCH_LABELS.items()}

# --------------------------------------------------------------------------------------
# 编译模式
# --------------------------------------------------------------------------------------
PACS_COMPILE_OPTIMIZED = "optimized"   # 大列表优化版：域名反转分段查表，4000+ 条也不慢
PACS_COMPILE_READABLE = "readable"     # 可读版：逐条 if，便于人工检查
PACS_COMPILE_MODES = [PACS_COMPILE_OPTIMIZED, PACS_COMPILE_READABLE]
PACS_COMPILE_MODE_LABELS = {
    PACS_COMPILE_OPTIMIZED: "优化版（推荐，规则多也快）",
    PACS_COMPILE_READABLE: "可读版（逐条 if，便于检查）",
}

# --------------------------------------------------------------------------------------
# 默认动作（没命中任何规则时）
# --------------------------------------------------------------------------------------
PACS_DEFAULT_ACTIONS = ["proxy", "direct"]
PACS_DEFAULT_ACTION_LABELS = {
    "proxy": "默认走代理",
    "direct": "默认直连",
}

# --------------------------------------------------------------------------------------
# ZeroOmega 导出形态
# --------------------------------------------------------------------------------------
PACS_OMEGA_ENTRY_NAME = "+自动模式"
PACS_OMEGA_MASTER_NAME = "+Master"
PACS_OMEGA_PORTABLE_NAME = "PAC 分流工作室"

# --------------------------------------------------------------------------------------
# 其它
# --------------------------------------------------------------------------------------
PACS_UI_HINT_OBJECT_NAME = "hintLabel"
PACS_MIN_WINDOW_W = 980
PACS_MIN_WINDOW_H = 660
PACS_IMPORT_PROGRESS_STEP = 200          # 导入时每处理多少条规则汇报一次进度
