# PAC 分流工作室（PAC Studio）

一个只做一件事的工具：**编辑 PAC 分流规则、让 Windows 走 PAC、和 ZeroOmega 的 PAC 互转**。

- 主程序：`PAC_Studio.py`
- 默认外部代理：`***已脱敏***-内网IP:20808`（与 `OmegaProfile.pac` 的 `+Master` 一致，可在设置里改）
- 界面：PySide6 · 全中文 · 所有耗时操作走工作线程 + 进度条

## 功能

| 能力 | 说明 |
| --- | --- |
| 规则编辑 | 域名后缀 / 通配域名 / 关键词 / URL 正则 / 主机名正则 / IP 段 / 全部流量，动作支持 DIRECT、PROXY、SOCKS5、混合；多选批量改、上下移、搜索、启停 |
| 编译 | 两种产物：**优化版**（几千条域名合并成查表，4000+ 条也快）与**可读版**（逐条 `if`，便于人看） |
| 让 Windows 走 PAC | 写 `HKCU\...\Internet Settings` 的 `AutoConfigURL` + `ProxyEnable=0`，并刷新 WinINET；**自动备份你原来的系统代理**，一键还原 |
| ZeroOmega 导入 | 解析 ZeroOmega 导出的 PAC（含 `+自动模式` → `+__ruleListOf_…` → 嵌套 `+__tempZeroRuleListPac` 这种三层结构），把规则展开成可编辑表格 |
| ZeroOmega 导出 | 生成与 ZeroOmega 原生导出一致的脚本，可直接粘贴回「自动切换模式 → PAC 脚本」 |
| 多方案 | 可保存多套规则（公司 / 家里 / 临时），一键切换 |
| 开机自动应用 | 写 `HKCU\...\Run`，开机静默执行 `--apply-pac` |
| 托盘 | 关闭窗口可最小化到托盘，托盘右键可快速应用 / 还原 |

## 快速开始

```bat
python PAC_Studio.py
```

1. 首次启动会自动建一个「默认方案」，默认动作 = 走代理 → `SOCKS5 ***已脱敏***-内网IP:20808`
2. 点「添加规则」，或直接「导入 ZeroOmega」把现有配置搬进来
3. 点「编译预览」看一眼脚本 → 点「应用到 Windows」
4. 不开心的时��点「还原原设置」，回到你原来的系统代理

命令行：

```bat
python PAC_Studio.py --apply-pac --silent      :: 静默应用（开机自启干的事）
python PAC_Studio.py --restore                 :: 还原系统代理
python PAC_Studio.py --compile-only out.pac    :: 只生成 PAC 文件
python PAC_Studio.py --version
```

## 目录结构

```
PAC_Studio.py              主入口（最终更新版）
pacs/
  constants.py             版本号、动作、匹配类型、默认代理
  paths.py  settings.py  settings_defaults.py  utils.py
  profiles.py              多方案存取
  sysproxy.py              Windows 系统代理（注册表 + 备份还原）
  autostart.py             开机自启
  pac/                     model / compiler / parser / omega_import / omega_export / builtin
  gui/                     mainwindow / rule_model / workers / theme / widgets / dialogs
_scaffold/                 启动与验证脚本（bat、冒烟、图标、打包、版本备份）
docs/                      设计说明与使用说明
version/                   每次更新的版本备份（日期-v序号）
data/                      运行期数据（方案、设置、PAC 产物）——不进仓库
```

## 验证

```bat
python -m compileall pacs PAC_Studio.py   :: 语法
python _scaffold/smoke_core.py            :: 导入/编译/导出/回读
python _scaffold/verify_pac_runtime.py    :: 用 Node + Windows JScript 真跑生成的 PAC
python _scaffold/smoke_gui.py             :: 离屏启动界面
python _scaffold/check_modules.py         :: 单文件行数上限 / 结构
```

实测（2026-10-28，样本 `G:\PAC\OmegaProfile.pac`）：

- 导入：5 个 profile → 展开 **4557** 条规则（直连 37 / 走代理 4520；域名后缀 4270、通配 4、主机名正则 2、URL 正则 281），耗时约 1.0 s
- 编译：优化版 363.1 KB / 256 ms，可读版 526.1 KB / 184 ms
- 回读：导出的 ZeroOmega 脚本重新导入，仍是 4557 条（往返一致）
- 运行期：Node 86 条用例全过；Windows JScript（cscript）12/12 通过

## 已知限制

1. **Windows 自带 IE/WinINET 对 `SOCKS5` 支持不完整**。Chrome / Edge / Firefox 有自己的 PAC 引擎，能正常按 SOCKS5 走；如果某个老程序不认，可在设置里把默认协议改成 HTTP 代理或混合模式。
2. `file:///` 形式的本机 PAC 通常有效，但个别浏览器要重启或等几秒才读取新设置。
3. ZeroOmega 里「`scheme === "http" && url.indexOf(...)` 这类多条件与（`&&`）组合」无法安全拆成单条规则，导入时只登记不转换（样本里 2 条）。需要的话可导出后在 PAC 里手工补。
4. 导入时会**折叠**只做「本机直连保护 + 一个出口」的 profile（如 `+Master`），因为本程序生成的脚本开头本来就对 localhost / 127.0.0.1 / ::1 / 纯主机名一律直连，语义等价。

## 安全

本项目不保存任何账号、密码、API Key，不需要 `.env`。它只读写：
`HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`（系统代理）、
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（仅在你勾选开机自启时）、
以及项目自己的 `data/` 目录。

## 许可

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）** 发布。

- 完整许可证条文见仓库根目录 [LICENSE](LICENSE)。
- 你可以自由使用、修改、分发，包括用于商业用途，无需另行获得授权。
- 若你修改后分发，或以网络服务方式提供本软件，必须按 AGPL-3.0 公开相应源代码。
- 本仓库自 2026-11-23 起改用 AGPL-3.0；此前已按 MIT / BSD-3-Clause 发布的版本，其接收者依原许可证获得的授权继续有效。
