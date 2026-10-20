# WxToOb：微信聊天记录一键存进 Obsidian

**从微信到 Claude，只差一次转发。** 聊天记录一键存成 Obsidian 笔记，随时交给 Claude 接着处理。

> **这是一个 demo。** 作者为自己的电脑写的，笔记目录、Python 路径等都写死成了作者的环境，没有做通用化，也不提供打包好的 App。
> 推荐用法：clone 下来，让 [Claude Code](https://claude.com/claude-code) 读一遍这个仓库，按你的环境改好再装。

在 Mac 版微信里多选聊天记录 →「转发到其他应用 → 选择电脑中的应用 →**存到 Obsidian**」，聊天记录就会变成 Obsidian 库里的一篇 Markdown 笔记，图片、文件一起存进库里，然后自动在 Obsidian 里打开这篇笔记。全程不需要快捷指令。

## 工作原理

```
微信「转发到其他应用」（微信打包成一个 zip）
  └─ 存到 Obsidian：macOS 分享扩展（沙盒）
       把 zip 放进 ~/Library/Application Support/WxToOb/queue/
         └─ launchd 发现 queue 非空，启动 process.sh
              ├─ zip 移到 archive/ 留底
              └─ wx2ob.py：解析「聊天记录.txt」→ 写 Markdown、复制附件 → 弹通知 → 打开 Obsidian
```

为什么分两段：分享扩展必须开沙盒，不能运行脚本，所以只负责把 zip 放进队列，转换交给 launchd 起的后台脚本。

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | macOS 14 及以上，Apple Silicon（`build.sh` 写死了 `arm64`） |
| 编译 | Xcode Command Line Tools（`xcode-select --install`）。**不需要 Xcode，也不需要 Apple 开发者账号**，用本机签名 |
| Python | `/opt/homebrew/bin/python3`，只用标准库 |
| 微信 | Mac 版 4.1.13 实测可用；其他版本导出格式可能不同 |

## 安装前先改这几处

| 位置 | 现在的值 | 改成 |
|---|---|---|
| `Sources/Converter/wx2ob.py` 的 `DEFAULT_ROOT` | `~/xuxu_note/xuxu_n/wx` | 你的 Obsidian 库里存微信记录的目录 |
| `Resources/process.sh` 的 `py` | `/opt/homebrew/bin/python3` | 你的 python3 路径 |
| 全仓库的 `com.xuxu.wxtoob` | 作者的 Bundle ID | 可选，换成你自己的 |

**注意：库不能放在 `~/Downloads`、`~/Desktop`、`~/Documents` 里。** 这几个目录受 macOS 隐私保护，launchd 起的后台脚本访问会报 `Operation not permitted`（`~/Downloads` 实测被拒）。库放在 iCloud Drive 里的情况没测过。

## 安装

```sh
git clone <本仓库> && cd wx_export_plugin
./build.sh
```

`build.sh` 依次完成：编译 → 本机签名 → 安装到 `~/Applications/WxToOb.app` → 注册分享扩展 → 安装后台任务 `com.xuxu.wxtoob.process`。构建日志在 `build/build.log`。

**装完要完全退出微信（⌘Q）再打开**，转发菜单里才会出现「存到 Obsidian」和它的图标。

## 日志和数据

都在 `~/Library/Application Support/WxToOb/`：

| 路径 | 内容 |
|---|---|
| `share.log` | 分享扩展：收到了什么、入队是否成功 |
| `process.log` | 后台转换：处理了哪个 zip、生成了哪篇笔记、退出码 |
| `launchd.err.log` | 后台脚本自身启动失败时的报错 |
| `archive/` | 每次转发的原始 zip，转换出问题时可以重跑 |

## 本机自测（不用打开微信）

```sh
# 把一个微信导出的 zip 直接交给分享扩展，走完整流程
swift tools/share.swift ~/Library/Application\ Support/WxToOb/archive/<某个>.zip

# 只测转换逻辑
cd Sources/Converter && python3 -m unittest test_wx2ob
```

## 让 Claude 帮你改

clone 之后在仓库目录里打开 Claude Code，直接说需求，比如：

- 「我的 Obsidian 库在 `~/Notes/Vault`，微信记录放到 `Inbox/微信` 下，帮我改好并安装」
- 「我是 Intel Mac，帮我改 build.sh」
- 「笔记里不要按日期分段，改成一条消息一个引用块」
- 「转发后没反应，帮我看日志排查」

Claude 能自己完成「改代码 → `./build.sh` → `swift tools/share.swift` → 看日志」这一整轮，不用你每次去微信里点。

## 卸载

```sh
launchctl bootout gui/$(id -u)/com.xuxu.wxtoob.process
rm ~/Library/LaunchAgents/com.xuxu.wxtoob.process.plist
pluginkit -r ~/Applications/WxToOb.app/Contents/PlugIns/WxShare.appex
rm -rf ~/Applications/WxToOb.app
rm -rf ~/Library/Application\ Support/WxToOb      # 日志和 zip 留底，按需保留
```

## 已知限制

- 用的是本机签名，只能在自己电脑上编译安装，编译出的 `.app` 拷到别的 Mac 上不一定能用。
- 只认微信「转发到其他应用」打出来的 zip（内含 `聊天记录.txt`）。认不出时间格式时，笔记会原文照录。
- 第一次安装、或改了图标之后，要重启微信才能看到变化。

版本号见 `VERSION`：修 bug 升补丁位，加功能升次版本。

许可证：MIT，见 `LICENSE`。
