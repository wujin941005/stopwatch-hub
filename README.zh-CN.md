# StopWatch Hub（中文说明）

<p align="center">
  <a href="README.md">English</a> | 简体中文
</p>

StopWatch Hub 把 **PrintSphere**、**CC Island** 和 M5Stack 官方
**M5StopWatch-UserDemo** 固件组合到 **M5Stack StopWatch C152** 上。设备仍然只运行
一份 ESP-IDF 固件，硬件仍由一套 M5Stack/Mooncake 框架管理；PrintSphere 与
CC Island 则作为两个独立 App，和官方表盘、秒表、闹钟、设置等原生 App 一起出现在启动器。

| App | 用途 | 当前状态 |
| --- | --- | --- |
| **CC Island** | AI 编程用量与主机监控 | 已集成并通过真机验证 |
| **PrintSphere** | 完整拓竹打印状态、相机与控制 | 完整移植 v1.6.2；本地 MQTT 与共存已通过真机验证 |

仓库采用混合许可证：CC Island 与本项目原创的 Hub 集成代码为 MIT；PrintSphere
衍生文件为 FNCL v1.1，未经版权方另行书面授权仅限非商业用途。分发本项目或用于商业
场景前请先阅读 [LICENSE](LICENSE) 和 [NOTICE.md](NOTICE.md)。

当前集成的是固定版本 PrintSphere v1.6.2 的完整源码，不是精简 LAN 状态页。合并固件
已经在 C152 真机完成编译、刷写和双 App 共存验证，共享 Wi-Fi、SNTP、RTC 持久化和
设备级时区均已运行。打印机、相机、控制、配网与 OTA 的全部组合仍按
[移植状态](docs/porting-status.md)逐项验收。

## 从这里开始

[选择使用路径](#选择使用路径) · [安装](#完整安装) ·
[PrintSphere](#printsphere) · [CC Island](#cc-island) ·
[常见问题](#常见问题)

StopWatch Hub 始终生成**一份合并固件**。不需要为两个 App 分别编译：安装一次后，
直接在官方启动器里使用 PrintSphere、CC Island，或同时使用两者。

### 选择使用路径

| 目标 | 手表侧配置 | 电脑端服务 | Bambu Cloud |
| --- | --- | --- | --- |
| 只看拓竹打印机 | 用打印机局域网信息配置 PrintSphere | 不需要 | 不需要；推荐 **Local only** |
| 只看 AI 用量/主机状态 | 配置共享 Wi-Fi 和 bridge 地址 | 电脑必须运行 CC Island bridge | 不需要 |
| 两个 App 都用 | 完成上面两条配置 | 只有 CC Island 需要 | 可选；先阅读下文的会话风险 |

### Clone 前准备

- **硬件：**仅支持 M5Stack StopWatch **C152**。不要刷到 PrintSphere 原版 Waveshare
  板或其他 M5Stack 产品。
- **固件构建：**需要 Git、Bash、USB 数据线和 ESP-IDF v5.5.4。Linux/macOS 可直接
  构建；Windows 推荐在 WSL2 中运行固件安装脚本。
- **CC Island 主机：**支持 Windows、macOS、Linux 和 WSL。安装
  [uv](https://docs.astral.sh/uv/)，并先登录希望 bridge 读取的 provider CLI。
- **PrintSphere Local only：**准备好打印机局域网 IP/主机名、序列号与 LAN Access Code。

项目不会提供带通用配置的预编译固件：CC Island 的 Wi-Fi、bridge 地址、布局与刷新策略
是编译输入；使用他人 `.env` 构建的 binary 还会包含对方的网络配置。

### Clone 并进入项目

```bash
git clone --recurse-submodules https://github.com/wujin941005/stopwatch-hub.git
cd stopwatch-hub
cp .env.example .env
```

如果已经 clone 但没有拉子模块，运行：

```bash
git submodule update --init --recursive
```

接着按[完整安装](#完整安装)编辑 `.env`、构建并刷机。首次启动后：

1. PrintSphere 用户通过 [Web Config](#printsphere-首次使用)配置打印机。
2. CC Island 用户启动并验证[电脑端 bridge](#运行-cc-island-bridge)。
3. 串口日志会显示 `station ready at ...`；也可在路由器 DHCP 客户端列表查看手表 IP。
   如果无法连接家庭 Wi-Fi，则使用下文说明的 PrintSphere setup AP。

## 两个 App 怎样进入原生固件

`scripts/install_firmware.sh` 会从锁定的 M5Stack V0.5 官方固件生成一棵构建目录，
再把本项目安装进去。只有这棵生成的官方固件构建目录会收到集成修改；锁定的
`vendor/PrintSphere` 子模块保持不变：

```text
M5StopWatch-UserDemo（一份合并后的 StopWatch-UserDemo 固件）
├── 官方 Mooncake App        表盘、秒表、闹钟、设置……
├── CC Island App            firmware/app_codex
│   └── 电脑端 bridge        Wi-Fi HTTP 轮询和/或 BLE NUS 推送
├── PrintSphere App          firmware/app_printsphere
│   └── PrintSphere v1.6.2   完整源码作为固件 service 参与构建
└── 共享平台
    ├── M5Stack HAL          显示、触摸、LVGL、PMU、音频、I2C、RTC、FAT
    ├── hub_wifi             两个 App 与官方配网页共用的 Wi-Fi 所有者
    └── hub_time             SNTP、UTC RTC 持久化和设备级时区
```

安装脚本明确完成五件事：

1. 把锁定版本的 M5Stack 官方固件 clone 到被 Git 忽略的 `build-firmware/`。
2. 复制 CC Island、PrintSphere 的 Mooncake App 外壳、图标、共享 Wi-Fi/时间服务和
   双 OTA 分区表。
3. 从 `vendor/PrintSphere` 物化完整 PrintSphere 源码，把它原先独占硬件的调用替换为
   M5Stack 适配层，同时保持上游子模块不变。
4. 在官方启动器与 CMake 中注册 `AppCodex` 和 `AppPrintSphere`。Mooncake 只创建一次
   它们的长期服务；用户进入或退出 App 时，再调用各自的 open/close 生命周期。
5. 生成一份合并的 `StopWatch-UserDemo` 镜像。PrintSphere OTA 只接受新的 Hub 合并
   镜像，避免误刷上游独立 PrintSphere 后删掉 CC Island 或官方 App。

因此硬件所有权始终清晰：两个 App 共用 Wi-Fi 和系统时间，但各自维护 UI、运行状态与
NVS namespace。PrintSphere 的打印机/Cloud 凭证保存在手表自己的 namespace；
CC Island 的 provider 凭证、本地日志与 OpenCode 数据库始终留在 bridge 主机，只把
最终显示数字传给手表。

## PrintSphere

启动器里的 **PrintSphere** App 保留上游 LAN/Cloud MQTT、Cloud REST 登录与 2FA、
Hybrid 数据源、多打印机、AMS 与完整错误详情、云端封面、本地 JPEG 相机、打印控制、
带 PIN 的 Web Config、Wi-Fi 扫描与 fallback AP、浏览器检测且与官方表盘共享的设备级时区、
屏幕旋转、提示音与自定义 WAV、
USB Improv 配网以及 OTA。

移植改变的是硬件归属，不是删功能：

- 显示、触摸、LVGL、PMU、音频、I2C 与文件系统仍只由 M5Stack 官方 HAL 初始化一次；
- PrintSphere 与 CC Island 共同使用一个 `hub_wifi`，官方 Badge 配置 AP 可临时接管后归还；
- PrintSphere 作为独立 Mooncake App 打开；退出时隐藏私有 UI、恢复亮度和方向，并暂停
  相机/封面重任务；
- Web Config 地址为 `http://手表IP:8080`；fallback AP 页面为
  `http://192.168.4.1:8080`，密码 `printsphere`；
- OTA 只接受合并后的 `StopWatch-UserDemo` 镜像，拒绝会覆盖其他 App 的上游独立镜像。

> [!WARNING]
> Bambu Cloud 登录使用的是非官方账号接口。在本项目测试的中国区账号上，完成邮箱验证码
> 登录后，Bambu Handy 与 Bambu Studio 的原有会话同时失效。我们不能据此断言拓竹实行
> 固定的“单会话政策”，但对主账号已经足以把 **Local only** 作为默认推荐。只有确实需要
> 云端能力、并能接受官方客户端可能需要重新登录时，才建议启用 Hybrid/Cloud。

最新正式镜像为 5,680,496 字节（`0x56ad70`），每个 6 MiB OTA 槽还剩
610,960 字节（`0x95290`，10%）。诊断版还在 C152 真机上完成了六轮完整的
“启动器 -> PrintSphere -> 启动器 -> CC Island -> 启动器”循环；每次打开
PrintSphere 都成功连接并订阅本地拓竹打印机 MQTT。实测内部堆历史最低值为
6,043 字节，所有采样任务栈至少还剩 1,420 字节；全程没有 OOM、分配失败、panic、
看门狗、栈溢出或重启。

### PrintSphere 首次使用

1. 刷入本仓库生成的 **StopWatch Hub 合并固件**；安装 Hub 后不要再刷上游独立版
   PrintSphere，否则会覆盖 CC Island 和官方 App。
2. 等待手表连接 `.env` 中配置的共享 Wi-Fi。连不上时可使用 PrintSphere fallback AP
   （密码 `printsphere`），打开 `http://192.168.4.1:8080`。
3. 在同一局域网打开 `http://手表IP:8080`。如果页面已锁定，在 PrintSphere 界面任意
   位置长按一秒，再输入手表显示的六位 PIN。
4. 日常使用推荐选择 **Local only**，填写打印机局域网地址与 Access Code。只有需要
   云端封面/元数据或兜底、并接受上面的官方客户端会话风险时，才选择 Hybrid/Cloud。
5. 确认浏览器检测出的时区并点击 **Apply**。时区会作为设备设置保存，由 PrintSphere
   和官方表盘共享。选择打印机后，从启动器打开 **PrintSphere** 即可。

固件内置 56 个常见 IANA 时区；如果浏览器报告的地区尚未收录，PrintSphere 会保留
当前设备时区，不会再强制改成 UTC。

这里的 8080 是手表的端口；CC Island bridge 也可以在电脑上使用 8080。两者位于不同
主机，不会冲突。

## CC Island

> 把 AI 编程用量和主机状态，搬到你的 M5Stack StopWatch 手表上。

<p align="center">
  <img src="firmware/tools/cc_island.svg" width="128" alt="CC Island 图标">
</p>

<p align="center">
  <img src="docs/cover.jpg" width="48%" alt="真机上的经典双行布局">
  <img src="docs/screenshots/codex-page.png" width="48%" alt="从手表帧缓冲抓取的 Codex 独立页面">
</p>

左边是第一版经典双行布局的真机照片；右边是加入电量底栏前的 Codex 独立页面帧缓冲截图，
当前固件保留相同主页面，并增加下文说明的电池图标与百分比底栏。

CC Island 把一块 **M5Stack StopWatch**（圆形 AMOLED，ESP32‑S3）变成 AI
编程用量与主机健康状态的小表盘。它支持 **Claude Code（橙）**、**Codex（蓝）**、
**OpenCode（紫）**，显示滚动窗口、重置倒计时、本地 token、API 等效价值与 PC 状态。

支持的 provider 与传输方式：
- **Claude Code / Codex / OpenCode** 三个 provider，可选经典双行布局，也可让
  Codex 与 OpenCode 各自独占一页
- **蓝牙 BLE** 与 **Wi‑Fi HTTP 轮询**两种传输，可并存
- **主机系统页**：电脑名、CPU、内存、磁盘占用与读写、网络上下行；支持自动轮播和左右滑动
- **手表电量栏**：所有 CC Island 页面底部显示分档电池图标与百分比，并用颜色区分充电与低电量

灵感来自 [CodexIsland](https://github.com/ericjypark/codex-island)（显示在 MacBook 刘海里）。
**本地优先，provider 凭证始终留在主机**：bridge 读取你 CLI 已经写好的凭证、查询各家官方用量接口、
从本地会话日志计算统计，再把最终数字通过**蓝牙 BLE** 或 **Wi‑Fi HTTP** 传给手表。

### CC Island 需要什么

与 PrintSphere 的本地打印机连接不同，CC Island 需要在 Windows、macOS、Linux 或
WSL 主机上运行一个轻量 companion bridge：

- provider CLI 保持登录在主机上，不在手表输入 provider 凭证；
- bridge 把 provider 接口和本地日志转换成紧凑的手表显示数据；
- 推荐 Wi-Fi polling 获得最完整体验，也可以用 BLE NUS 做低频推送；两种传输可同时编入固件；
- bridge 应保持运行以提供新数据；短暂断线时手表显示 last-good 缓存，不会清零。

安装和验证命令见[运行 CC Island bridge](#运行-cc-island-bridge)。

CC Island 不需要 Bambu 凭证，PrintSphere 也不需要电脑上的 Claude、Codex 或
OpenCode 凭证；两者只共享设备级基础服务。

## 项目沿革

本项目的 CC Island 代码基础来自
[alexjc-tech/cc-island](https://github.com/alexjc-tech/cc-island)。固件底座来自 M5Stack
的 [M5StopWatch-UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo)；AI 用量伴侣的
产品思路和最初的 provider 鉴权方案则改编自 Eric Park 的
[CodexIsland](https://github.com/ericjypark/codex-island)。三者分别代表直接上游、固件底座和
产品灵感，因此在这里明确区分。

## CC Island 使用方式

| 目标 | 传输 | `.env` | 主机支持 |
| --- | --- | --- | --- |
| 只看 AI 用量 | Wi‑Fi | `CC_SYSTEM_MONITOR=false` | Windows、macOS、Linux、WSL |
| AI 用量 + 主机监控 | Wi‑Fi | `CC_SYSTEM_MONITOR=true` | Windows、macOS、Linux、WSL |
| 低频推送 | BLE（`bleak`） | 均可 | Windows、macOS、Linux |

功能最完整的组合是 `CC_LAYOUT=pages` + Wi‑Fi polling，再按需开启系统页；偏好原版
高密度界面则使用 `rows`。同一份固件也可以同时保留 BLE 与 Wi‑Fi。provider、bridge
或 Wi‑Fi 短暂异常时会保留最后数据，手表重启后也能从 Flash 恢复。

### 三平台支持矩阵

| 能力 | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Codex 登录与本地日志 | `~/.codex` | `~/.codex` | `~/.codex` |
| Claude 登录与本地日志 | `~/.claude/.credentials.json` | Keychain，再回退凭证文件 | `~/.claude/.credentials.json` |
| OpenCode 本地用量 | XDG data / `opencode.db` | XDG data / `opencode.db` | XDG data / `opencode.db` |
| 主机指标 | `psutil`，PowerShell 兜底 | `psutil`，原生命令兜底 | `psutil`，`/proc` 兜底 |
| Wi‑Fi polling | 支持 | 支持 | 支持 |
| BLE push | 支持 | 支持 | 支持（需要 BlueZ） |

Bridge 运行在 WSL 时，还会自动检查挂载进来的 Windows 用户目录，因此 OpenCode
安装在 Windows 上也能读取。自定义目录可以通过 `CODEX_HOME`、
`CLAUDE_CONFIG_DIR`、`OPENCODE_DB` 明确指定。

## CC Island 显示内容

内置两种显示布局：

- **`rows`**：经典紧凑布局，从 Claude Code、Codex、OpenCode 中任选两个放在同一页
- **`pages`**：Codex 一页、OpenCode 一页，并可加入系统页；有空间完整显示各窗口
  的重置时间和 OpenCode 月度配额

运行 `scripts/install_firmware.sh` 前设置 `CC_LAYOUT=rows|pages`。系统监控默认关闭；
设置 `CC_SYSTEM_MONITOR=true` 后才会采集主机指标并加入系统页。两种布局均可显示：

- provider **用量窗口**：百分比、品牌色进度条、重置倒计时
- **今日 token 数**与 **API 等效价值**
- 5 小时用量首次超过 80% 时**振动提醒**
- OpenCode 配置 Go auth cookie 后显示**真实配额**（5 小时 / 每周 / 每月及重置）；
  未配置时显示本地今日 / 7 天用量

界面以 `~$` 开头的金额表示 **API 等效价值**，不是实际账单。Claude、Codex 与能够
识别模型的 OpenCode 都使用 OpenRouter 当前公开价格目录折算；未知 OpenCode 模型才
回退它自己记录的金额。使用 Coding Plan、OpenCode Go 或其他订阅时，不会按这个金额
重复扣费。

可选的**系统页**显示 bridge 主机的电脑名、CPU、内存、磁盘占用与读写速率、网络
上下行。运行在 WSL 时优先通过 PowerShell 读取 Windows 主机，互操作不可用时才回退
到 WSL 虚拟机。原生 Windows、macOS 与 Linux 使用 `psutil`，并分别保留 PowerShell、
原生命令和 `/proc` 兜底。系统监控仍默认关闭，因为它和 AI 用量是独立功能。

左右滑动可切页；**橙色按钮**切换 `AUTO` / `MAN` 自动或手动轮播；**蓝色按钮**
请求立即刷新。设置 `CC_AUTO_SWITCH_MS=0` 可让固件默认从手动模式启动。底栏会在所有
页面持续显示 `AUTO`/`MAN` 与手表电量；百分比后的 `+` 表示已接入外部电源。

## CC Island 架构

```
  Windows / macOS / Linux（大脑）                手表 / CC Island app（脸）
  bridge/codexisland_bridge.py                   firmware/app_codex
   · Claude/Codex 接口 + 本地日志                  · 双行或 provider 独立页面（LVGL）
   · OpenCode SQLite + 可选 Go 配额                · 滑动 + 自动/手动轮播
   · 三平台原生指标 + WSL Windows 集成               · 可选主机系统页
   · 30 秒刷新 + 6 小时 last-good 回退              · Wi-Fi polling + BLE NUS 接收
   · GET /stats ─────────HTTP (Wi‑Fi)─────────▶   · 蓝键立即刷新
   · 紧凑 JSON 推送 ───蓝牙(NUS)──────────────▶   · Flash 持久化最后有效数据
```

手表是被动的 BLE 外设（Mac/PC 连上写入），也可连 Wi‑Fi 定时轮询。**token、日志、
API 凭证和 Cookie 都不会传到手表**，只传算好的数字。

## 完整安装

### 构建并刷入合并固件

需要 [ESP‑IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html)。
集成脚本需要 Bash：Linux/macOS 可直接运行；Windows 推荐使用 WSL2 构建固件。手表刷好后，
CC Island bridge 仍可在 Windows PowerShell 原生运行。

`.env` 同时包含需要编进手表的配置，以及只由 bridge 运行时读取的配置：

| 配置 | 谁读取 | 要重新刷表？ | 要重启 bridge？ |
| --- | --- | --- | --- |
| `CC_WIFI_*`、`CC_BRIDGE_*`、`CC_POLL_MS` | 固件安装脚本 | 要 | 不要 |
| `CC_LAYOUT`、`CC_AUTO_SWITCH_MS` | 固件安装脚本 | 要 | 不要 |
| `CC_SYSTEM_MONITOR` | 固件安装脚本 + bridge | 要 | 要 |
| `OPENCODE_GO_*`、`OPENCODE_DB` | bridge | 不要 | 要 |
| `CODEX_HOME`、`CLAUDE_CONFIG_DIR` | bridge | 不要 | 要 |
| `CC_PRICING_*`、`CC_CODEX_FALLBACK_MODEL` | bridge | 不要 | 要 |

provider 密钥不会写入固件。Codex、Claude 复用 bridge 主机已有的 CLI 登录凭证；
OpenCode 本地统计只读查询它的 SQLite 数据库。

```bash
# 在 stopwatch-hub 仓库根目录运行
git submodule update --init --recursive
if [ ! -f .env ]; then cp .env.example .env; fi  # 只在首次配置时创建
# 编辑 Wi-Fi、bridge 地址、布局、刷新间隔、可选系统监控和 OpenCode Go 配置
./scripts/install_firmware.sh          # clone 出厂固件并集成 app（到 ./build-firmware）
. ~/esp/esp-idf/export.sh
cd build-firmware
idf.py build
idf.py -p /dev/ttyACM0 flash  # Linux/WSL 示例；其他平台按下表替换
```

按构建环境替换示例端口：

| 构建环境 | 常见端口 | 说明 |
| --- | --- | --- |
| Linux | `/dev/ttyACM0` | 权限不足时把用户加入 `dialout` |
| macOS | `/dev/cu.usbmodemXXXX` | 重连后尾号可能变化 |
| Windows ESP-IDF Shell | `COM3` | 安装脚本仍需要 Bash，推荐 WSL2 |
| WSL2 | `/dev/ttyACM0` | 先用 `usbipd` 把 USB 设备附加到 WSL |

首次安装应使用 `idf.py flash`，让合并分区表与 App 一起写入。除非明确要清空 Wi-Fi、
打印机 profile、Cloud token 等 NVS 配置，否则不要运行 `erase-flash`。
`install_firmware.sh` 只把 `CC_*` 配置写进同样被忽略的 `build-firmware/`；Git 跟踪
的源码只保留占位值。Wi-Fi 名称和密码会随固件写入手表；provider API 凭证与
OpenCode Cookie 始终留在 bridge 主机。PrintSphere 也可在运行时配 Wi-Fi，并把打印机、
Cloud 等设置放在自己的 NVS namespace；它的低频状态服务与 8080 端口 Web Config
随 Mooncake 创建启动。打开 **CC Island** 后才会启动它的 BLE/HTTP 传输；打开
**PrintSphere** 后显示完整界面并启用屏幕、相机等 App 范围的工作。

> [!CAUTION]
> 绝对不要公开上传使用个人 `.env` 构建的 `StopWatch-UserDemo.bin`：镜像里包含 Wi-Fi
> 凭证和 bridge 地址。公开 Release 必须在没有个人环境文件的情况下构建，再让用户通过
> setup AP/USB 自行配网。README 记录的真机测试镜像不会被 Git 跟踪。

重启后先确认设备服务正常，再配置任一 App：

```bash
curl http://手表IP:8080/api/health
```

应看到 `"status":"ok"`、`"wifi_connected":true`，且系统时间可信；串口日志也会以
`station ready at ...` 输出手表 IP。

### 配置 PrintSphere

手表重新连网后打开 `http://手表IP:8080`，选择 Hybrid、Cloud 或 local-only 模式，
配置打印机连接，并确认浏览器检测的时区。fallback AP 与 PIN 解锁过程见
[PrintSphere 首次使用](#printsphere-首次使用)。这一步不依赖 CC Island bridge。

### 运行 CC Island bridge

Wi-Fi 与 BLE 两种模式任选其一。

先安装一次 [uv](https://docs.astral.sh/uv/getting-started/installation/)，再创建锁定的
运行环境。Windows PowerShell、macOS、Linux 使用相同命令：

```console
uv sync
```

Wi‑Fi 模式三平台均推荐：

```console
uv run python bridge/codexisland_bridge.py --serve 8080
```

bridge 会自动读取 `.env`。OpenCode 本地用量无需额外配置；可选的 `OPENCODE_GO_*`
用于启用真实 Go 配额。`CC_SYSTEM_MONITOR=true` 会同时开启主机指标采集和固件系统页；
修改后需重新运行安装脚本、编译并刷入固件。浏览器可访问 `/` 看文本、`/json` 看完整
数据、`/stats` 看手表载荷。

在手表打开 CC Island 前，先验证实际载荷接口：

```bash
curl http://127.0.0.1:8080/stats
```

Wi-Fi polling 还应从局域网另一台设备访问 `http://bridge局域网IP:8080/stats`。如果
localhost 正常但局域网地址打不开，应先处理防火墙、监听地址或 WSL 网络，再排查手表。

蓝牙模式（通过 `bleak` 支持 Windows / macOS / Linux）：

```console
uv run python bridge/codexisland_bridge.py --ble 5
```

macOS 首次运行会弹蓝牙权限；Linux 需要可用的 BlueZ/D-Bus。仓库自带的登录自启脚本
目前只负责 macOS：`./scripts/setup_autostart.sh`。使用 `--json` 或不带参数可只检查数据。

## 使用 CC Island

- **自动刷新（Wi‑Fi）**：源码模板默认 10 秒，`.env.example` 使用 5 秒；provider 数据
  缓存 30 秒；开启后系统指标约 4 秒刷新，所以手表 5 秒 polling 不会每次都请求 provider
- **断线缓存**：provider 刷新失败后，bridge 最多 6 小时继续返回最后一次成功数据。手表也会
  在内存保留最新有效 Codex payload，并最多每 5 分钟写入一次 Flash；重新打开 app 或设备重启时
  如果 bridge 不可达，会先显示缓存，不会把页面清成 0。
- **自动刷新（BLE）**：每 N 分钟（默认 5；Anthropic 接口会限流，别低于几分钟）。
- **切换页面**：左右滑动；源码兜底值是每 5 秒自动轮播，**橙键**切换 `AUTO`
  （按定时器轮播）/ `MAN`（停留在当前页，直到手动滑动）；
  `.env.example` 设置了 `CC_AUTO_SWITCH_MS=0`，所以按示例生成的固件默认是手动模式
- **手动刷新**：按**蓝键**，手表振动并请求立即刷新（5 秒防抖）。
- **退出 app**：同时长按**两个按钮**（出厂固件的“回主页”）。

## 自定义 CC Island

- **本地配置** — 复制 `.env.example` 为 `.env`；`CC_WIFI_*`、`CC_BRIDGE_*`、
  `CC_POLL_MS` 控制 Wi-Fi，`CC_LAYOUT=rows|pages` 与 `CC_AUTO_SWITCH_MS` 控制页面，
  `CC_SYSTEM_MONITOR=true|false` 同时控制系统指标采集和系统页。`.env` 与
  `build-firmware/` 都不会进入 Git
- **双行 provider / 系统页** — `firmware/app_codex/app_codex_config.h` 中的
  `kTopProvider` / `kBottomProvider`（`"c"` Claude / `"x"` Codex / `"o"`
  OpenCode）和 `kShowSystemPage`；独立页面布局目前固定生成 Codex、OpenCode 页
- **Wi-Fi 默认模板** — `firmware/app_codex/net/net_config.h`
- **配色 / 告警阈值** — `firmware/app_codex/app_codex.cpp`
  （`kClaudeColor` / `kCodexColor` / `kOpencodeColor` / `kAlertThreshold`）
- **Go 配额配置** — 环境变量 `OPENCODE_GO_WORKSPACE_ID` / `OPENCODE_GO_AUTH_COOKIE`
- **真机帧缓冲截图** — USB 连接后运行：

  ```console
  uv run --with pyserial --with pillow python tools/screenshot.py out.png --port /dev/ttyACM0
  ```

  开发调试时加 `--advance 1`（或 `-1`）可在截图前切换页面
- **启动图标 / provider Logo** — `firmware/tools/cc_island.svg` 是 CC Island
  自己的三色监控图标；其他 SVG 只用于标识 provider。运行下面命令可重新生成固件位图：
  ```bash
  uv run --with svglib --with pillow --with reportlab --with rlpycairo \
    python firmware/tools/gen_icons.py
  python firmware/tools/gen_printsphere_icon.py
  ```
- **动态定价** — bridge 每 6 小时刷新 OpenRouter 公开的
  [`/api/v1/models`](https://openrouter.ai/api/v1/models)，并保留磁盘 last-good 缓存和
  小型离线兜底表。可用 `CC_PRICING_REFRESH_HOURS`、`CC_PRICING_CACHE` 覆盖默认值；
  `CC_CODEX_FALLBACK_MODEL` 决定隐藏模型 `codex-auto-review` 的等效计价，默认
  `gpt-5.6-sol`。OpenCode 的订阅/router provider ID 与模型发布者不一致时，会在结果
  唯一的前提下按公开模型名匹配

## CC Island 数据来源与金额口径

- **Codex**：使用 `CODEX_HOME/auth.json`（默认 `~/.codex/auth.json`）中的 access
  token 读取用量窗口，并解析 session JSONL 统计今天的 token；WSL 还会自动检查
  Windows 用户目录
- **Claude Code**：复用 `CLAUDE_CODE_OAUTH_TOKEN`、macOS Keychain 或
  `CLAUDE_CONFIG_DIR/.credentials.json`（默认 `~/.claude/.credentials.json`）读取官方
  用量接口；今天的 token 来自各平台 `~/.claude/projects/**/*.jsonl`
- **OpenCode**：只读查询官方 XDG data 目录，三平台通常都是
  `~/.local/share/opencode/opencode.db`，也会识别 beta/dev channel 数据库；可用
  `OPENCODE_DB` 或 `--db` 覆盖。Bridge 按 assistant message 的发生时间汇总各类 token，
  跨日继续旧 session 也不会漏算，并按时间、provider、模型与 token 指纹去除重复的
  subagent 调用。已识别模型按 OpenRouter 折算等效价值，即使 Coding Plan 记录金额为 0
  也能显示；未知模型和旧数据库结构才回退 OpenCode 的记录金额。`/json` 仍以
  `actual_t` / `actual_d` 保留记录金额供诊断。配置 `OPENCODE_GO_*` 后才会额外读取 Go
  订阅窗口，并缓存 5 分钟
- **系统指标（可选）**：仅在 `CC_SYSTEM_MONITOR=true` 时采集；原生 Windows、macOS、
  Linux 使用 `psutil`，并有平台原生兜底。WSL 优先通过 PowerShell 读取 Windows 主机，
  失败后才显示 WSL 自身。关闭时 Bridge 不采集，也不会在 payload 中发送 `sys`
- **`~$` 等效价值**：Claude、Codex 与已识别的 OpenCode 模型按 OpenRouter 动态目录
  估算，不是 Coding Plan
  或订阅账单；bridge 只下载公开价格目录，不会上送本地凭证、prompt 或 usage。先精确
  匹配模型，再处理日期/provider 别名与离线兜底；仍未识别的模型继续计入 token，并在
  `/json` 的 pricing diagnostics 中列出，OpenCode 同时保留记录金额作为兜底。token
  总量分别计入非缓存 input、cached input、cache write 与 output 各一次；Codex 的
  reasoning 已包含在 output 中不重复相加，OpenCode 单独报告的 reasoning 按 output
  价格加入一次

最初的 provider 鉴权与本地日志读取方案改编自
[CodexIsland](https://github.com/ericjypark/codex-island)；OpenCode、Wi-Fi polling、
系统监控、页面布局与交互均在本项目中实现。

## 参与贡献

欢迎提交 PR，尤其欢迎增加更多 AI coding provider 和平台集成。新增 provider 时，请让
凭证始终留在主机，并按实际需要一并补齐 Bridge 数据采集、手表紧凑 payload、固件行或
独立页面、配置项、测试以及中英文文档。同时请明确区分真实订阅配额、本地 token 统计和
API 等效金额估算，避免让用户误以为估算值是实际账单。

## 常见问题

- **bridge 找不到手表** → 先在表上打开 CC Island app（每次重启后首次打开才开始广播）；
  检查 Windows/macOS 蓝牙权限，Linux 则检查 BlueZ 与 D-Bus。
- **Wi‑Fi 模式手表空白** → 确认 bridge 在手表同一网络可达（手机上 `curl http://<host>:<port>/stats` 试试）；检查下面的 WSL 网络打通。
- **`SSL: CERTIFICATE_VERIFY_FAILED`** → 重新执行 `uv sync`；锁定环境已包含
  `certifi`，bridge 会优先使用它的 CA 证书包。
- **编译报 `nimble/nimble_port.h` 找不到** → BLE 没启用：删**项目根目录**的 `sdkconfig`（不是 build/ 里的）再 `idf.py reconfigure`。
- **链接报 `undefined reference to AppCodex`** → 新增文件后跑一次 `idf.py reconfigure`。
- **Apple 芯片报 `incompatible architecture`** → Intel 版 ninja 把工具链拖成 x86_64：`brew install ninja`，并把 `/opt/homebrew/bin` 放到 PATH 最前。
- **Go 配额报鉴权错误** → `auth` cookie 过期了：重新 F12 导出一次。
- **CLI 能用，但 bridge 提示鉴权或数据库不存在** → CLI 与 bridge 使用了不同的 Home
  （常见于 WSL、service、`sudo` 或自定义 XDG 目录）；明确设置 `CODEX_HOME`、
  `CLAUDE_CONFIG_DIR` 或 `OPENCODE_DB`。
- **原生 Windows 下手表连不上 Wi-Fi 模式** → 用管理员 PowerShell 放行 TCP 8080：

  ```powershell
  netsh advfirewall firewall add rule name="cc-island" dir=in action=allow protocol=TCP localport=8080
  ```
- **Codex 显示 `network unreachable` / `network timeout`** → 这是 bridge 到官方接口的
  网络问题，不是 Codex 登录失效。检查运行进程的 DNS 与代理环境；尤其 `sudo` 常会清掉
  `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`，应把它们写进 service unit 或使用普通用户启动。
  旧版本会把同一种传输错误误显示为 `http 0`。

### WSL2 网络打通（Wi‑Fi 模式）

WSL2 默认 NAT，手表无法直接访问 WSL 里监听的端口，二选一：
- **镜像网络**（Win11 22H2+）：在 `%UserProfile%\.wslconfig` 加入：
  ```ini
  [wsl2]
  networkingMode=mirrored
  ```
  bridge 端口即可经 Windows 主机 IP 访问。
- **端口代理**（任意 Windows，管理员 PowerShell）：
  ```powershell
  netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=8080 connectaddress=<wsl-ip>
  netsh advfirewall firewall add rule name="cc-island" dir=in action=allow protocol=TCP localport=8080
  ```
  WSL 里 `hostname -I` 查 `<wsl-ip>`，`net_config.h` 的 `host` 填 **Windows 主机 IP**。
  bridge 会优先读取 Windows 主机指标，只有 PowerShell 互操作失败时才显示 WSL 自身数据。

## 致谢与商标

- 维护版 fork 自 [alexjc-tech/cc-island](https://github.com/alexjc-tech/cc-island)（MIT）。
- 基于 M5Stack 的 [M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo)（MIT）。
- 灵感来自 Eric Park 的 [CodexIsland](https://github.com/ericjypark/codex-island)。
- BLE 传统广播包修复基于 [@xiaoyuanzi1230](https://github.com/xiaoyuanzi1230)
  提交的 [PR #1](https://github.com/alexjc-tech/cc-island/pull/1)。
- CC Island 的启动图标是独立设计的“三色 provider 环 + 监控脉冲”；provider 行内 Logo
  来自 **Anthropic/Claude** 与 **OpenAI** 的品牌标识（经 simple‑icons / lobe‑icons）。
  相关标识为各自所有者的商标，此处仅用于标识对应服务；本项目与 Anthropic、OpenAI
  无隶属或背书关系。

## 许可证

这是混合许可证仓库。CC Island 与原有通用集成代码使用 MIT；PrintSphere 衍生移植文件
使用 FNCL v1.1，未经另行授权仅限非商业用途。详见 [LICENSE](LICENSE)、
[NOTICE.md](NOTICE.md) 和各源码文件的 SPDX 标识。
