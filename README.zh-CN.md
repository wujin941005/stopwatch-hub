# CC Island（中文说明）

> 把 Claude Code 和 Codex 的用量额度，搬到你的 M5Stack StopWatch 手表上。

[English README](README.md)

CC Island 把一块 **M5Stack StopWatch**（圆形 AMOLED，ESP32‑S3）变成一个 AI 用量小表盘：
单页同时显示 **Claude Code（橙）** 和 **Codex（蓝）** 的 5 小时 / 7 天用量、重置倒计时，以及今日花费与 token。

灵感来自 [CodexIsland](https://github.com/ericjypark/codex-island)（显示在 MacBook 刘海里）。
**本地优先、设备上不存任何密钥**：Mac 端的小程序读取你 CLI 已经写好的凭证、查询各家官方用量接口、
从本地会话日志算花费，再把算好的数字通过**蓝牙 BLE** 推到手表。

## 显示内容

每家（Claude / Codex）在同一块圆屏上：
- **5 小时窗口**用量（大号百分比 + 品牌色进度条）
- **7 天窗口**用量
- 5 小时窗口的**重置倒计时**
- **今日花费**（等效美元）与 **token 数**（来自本地日志）
- 5 小时用量首次超过 80% 时**振动提醒**

按**蓝色按钮（G1）**可即时刷新；平时按定时自动刷新。

## 架构

```
  Mac（大脑）                                   手表 / CC Island app（脸）
  bridge/codexisland_bridge.py                 firmware/app_codex
   · 读 ~/.codex/auth.json                       · NimBLE Nordic-UART-Service 服务端
   · 读钥匙串 "Claude Code-credentials"          · 解析 JSON，画上下两行（LVGL）
   · 调各家官方用量接口                          · 蓝键(G1) → 请求刷新
   · 从 ~/.claude、~/.codex 日志算花费           · 过阈值振动
   · 推紧凑 JSON  ────────蓝牙(NUS)────────▶     · 显示 Anthropic / OpenAI 官方图标
```

手表是被动的 BLE 外设，Mac 是主机，主动连接并写入数据。**token 和日志永不离开 Mac**，只传算好的数字。

## 快速开始

**1. 刷固件**（需要 [ESP‑IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html)）

```bash
./scripts/install_firmware.sh          # clone 出厂固件并集成 app（到 ./build-firmware）
. ~/esp/esp-idf/export.sh
cd build-firmware && idf.py build && idf.py -p /dev/cu.usbmodemXXXX flash
```
刷完后在表上**打开一次 CC Island app**（蓝牙才开始广播）。

**2. 跑 Mac 端 bridge（开机自启）**

```bash
./scripts/setup_autostart.sh           # 默认每 5 分钟刷新一次
```
首次运行 macOS 会弹**蓝牙权限**窗口 → 点【允许】。之后它自动连上手表并推送。

> 想手动跑：`python3 bridge/codexisland_bridge.py --ble 5`（或 `--json` 只打印数字）。

## 使用

- **自动刷新**：每 N 分钟（默认 5；Anthropic 接口会限流，别低于几分钟）。
- **手动刷新**：按**蓝键(G1)**，手表振动并让 Mac 立即推送（5 秒防抖）。
- **退出 app**：同时长按**两个按钮**（出厂固件的“回主页”）。

## 常见问题

- **bridge 找不到手表** → 先在表上打开 CC Island app（每次重启后首次打开才开始广播）；确认 Mac 给了蓝牙权限。
- **`SSL: CERTIFICATE_VERIFY_FAILED`** → python.org 的 Python 没装 CA 证书：`pip install --user certifi`。
- **编译报 `nimble/nimble_port.h` 找不到** → BLE 没启用：删**项目根目录**的 `sdkconfig`（不是 build/ 里的）再 `idf.py reconfigure`。
- **链接报 `undefined reference to AppCodex`** → 新增文件后跑一次 `idf.py reconfigure`。
- **Apple 芯片报 `incompatible architecture`** → Intel 版 ninja 把工具链拖成 x86_64：`brew install ninja`，并把 `/opt/homebrew/bin` 放到 PATH 最前。

## 致谢与商标

- 基于 M5Stack 的 [M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo)（MIT）。
- 灵感来自 Eric Park 的 [CodexIsland](https://github.com/ericjypark/codex-island)。
- 图标位图来自 **Anthropic/Claude** 与 **OpenAI** 的品牌标识（经 simple‑icons / lobe‑icons），
  相关标识为各自所有者的商标，此处仅用于标识对应服务；本项目与 Anthropic、OpenAI 无隶属或背书关系。

## 许可证

MIT，见 [LICENSE](LICENSE)。
