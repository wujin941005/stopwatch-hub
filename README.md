# StopWatch Hub

<p align="center">
  English | <a href="README.zh-CN.md">简体中文</a>
</p>

StopWatch Hub combines **PrintSphere** and **CC Island** with M5Stack's original
**M5StopWatch-UserDemo** firmware for the **M5Stack StopWatch C152**. The watch
still runs one ESP-IDF image and one M5Stack/Mooncake hardware owner; PrintSphere
and CC Island are installed as independent launcher Apps beside the stock watch
faces, stopwatch, alarm, settings, and other factory Apps.

| App | Purpose | Status |
| --- | --- | --- |
| **CC Island** | AI coding usage and host monitoring | Integrated and device-validated |
| **PrintSphere** | Complete Bambu printer display and control | Full v1.6.2 port; local MQTT and coexistence device-validated |

The repository contains mixed-license code: CC Island and the original Hub
integration code are MIT, while PrintSphere-derived files are FNCL v1.1 and
restricted to non-commercial use unless separately licensed. Review
[LICENSE](LICENSE) and [NOTICE.md](NOTICE.md) before redistributing or using the
combined firmware commercially.

The complete pinned PrintSphere v1.6.2 source is integrated as a launcher App,
not reduced to a LAN status page. The combined firmware has been built, flashed,
and run on a physical C152 with both Apps, shared Wi-Fi, SNTP, RTC persistence,
and device-wide time-zone handling active. End-to-end acceptance for every
printer, camera, control, provisioning, and OTA combination is still tracked in
the [porting status](docs/porting-status.md).

## Start here

[Choose a path](#choose-a-path) · [Install](#detailed-setup) ·
[PrintSphere](#printsphere) · [CC Island](#cc-island) ·
[Troubleshooting](#troubleshooting)

StopWatch Hub always builds **one combined firmware image**. You do not need a
different build for each App: install it once, then use PrintSphere, CC Island,
or both from the stock launcher.

### Choose a path

| Goal | Watch setup | Computer service | Bambu Cloud |
| --- | --- | --- | --- |
| Bambu printer display only | Configure PrintSphere with printer LAN details | Not required | Not required; **Local only** is recommended |
| AI usage/host display only | Configure shared Wi-Fi and bridge address | CC Island bridge must run on the host | Not required |
| Both Apps | Complete both setup paths | Required only for CC Island | Optional; read the session warning below |

### Before cloning

- **Hardware:** M5Stack StopWatch **C152 only**. Do not flash this image to the
  original Waveshare PrintSphere boards or another M5Stack product.
- **Firmware build:** Git, Bash, a USB data cable, and ESP-IDF v5.5.4. Linux and
  macOS work directly; Windows users should use WSL2 for the firmware installer.
- **CC Island host:** Windows, macOS, Linux, and WSL are supported. Install
  [uv](https://docs.astral.sh/uv/) and sign in to the provider CLIs you want the
  bridge to read.
- **PrintSphere Local only:** have the printer LAN IP/hostname, serial number,
  and LAN Access Code ready.

There is intentionally no universal preconfigured binary: CC Island's Wi-Fi,
bridge address, layout, and refresh behavior are build inputs. A binary built
with somebody else's `.env` would also contain that person's network settings.

### Clone and enter the project

```bash
git clone --recurse-submodules https://github.com/wujin941005/stopwatch-hub.git
cd stopwatch-hub
cp .env.example .env
```

If the repository was already cloned without submodules, run:

```bash
git submodule update --init --recursive
```

Then follow [Detailed setup](#detailed-setup) to edit `.env`, build, and flash.
After the first boot:

1. PrintSphere users configure the printer through
   [Web Config](#printsphere-first-use-guide).
2. CC Island users start and verify the
   [host bridge](#run-the-cc-island-bridge).
3. The watch IP is shown in the serial log as `station ready at ...`; it is also
   visible in the router's DHCP client list. If station Wi-Fi is unavailable,
   use the PrintSphere setup AP documented below.

## How the two Apps live in the factory firmware

`scripts/install_firmware.sh` generates a build tree from the pinned M5Stack
V0.5 factory firmware and installs this project into it. Only that generated
factory checkout receives the integration edits; the pinned PrintSphere
submodule remains unchanged:

```text
M5StopWatch-UserDemo (one combined StopWatch-UserDemo image)
├── stock Mooncake Apps       watch faces, stopwatch, alarm, settings, ...
├── CC Island App             firmware/app_codex
│   └── host bridge           Wi-Fi HTTP polling and/or BLE NUS push
├── PrintSphere App           firmware/app_printsphere
│   └── PrintSphere v1.6.2    full source materialized as a firmware service
└── shared platform
    ├── M5Stack HAL           display, touch, LVGL, PMU, audio, I2C, RTC, FAT
    ├── hub_wifi              one station/AP owner for both Apps and stock setup
    └── hub_time              SNTP, UTC RTC persistence, and device time zone
```

The installer performs five deliberate steps:

1. Clone the pinned M5Stack factory firmware into the ignored
   `build-firmware/` directory.
2. Copy the CC Island and PrintSphere Mooncake App shells, icons, shared Wi-Fi
   and time services, and the dual-OTA partition table into that checkout.
3. Materialize the complete pinned PrintSphere source from
   `vendor/PrintSphere`, replacing standalone hardware ownership with asserted
   M5Stack adapters while leaving the upstream submodule unchanged.
4. Register `AppCodex` and `AppPrintSphere` in the factory launcher and CMake
   build. Mooncake creates their long-lived services once, then calls each App's
   open/close lifecycle as the user enters or leaves it.
5. Build one combined `StopWatch-UserDemo` image. PrintSphere OTA accepts only
   another combined Hub image, so an upstream standalone image cannot silently
   remove CC Island or the stock Apps.

This division keeps hardware ownership unambiguous. Both Apps share the Wi-Fi
station and system clock, but use separate App state and NVS namespaces.
PrintSphere printer/cloud credentials stay on the watch in its namespace;
CC Island's provider credentials, local logs, and OpenCode database stay on the
bridge host and only computed display values reach the watch.

## PrintSphere

The **PrintSphere** App preserves upstream LAN and Cloud MQTT, Cloud REST login
and 2FA, hybrid source selection, multiple printers, AMS/error detail, cover
preview, supported local JPEG cameras, printer controls, Web Config + PIN,
Wi-Fi scan/fallback AP, browser-detected per-device time zone shared with the
official watch faces, display rotation, sound events/custom WAV,
USB Improv provisioning and OTA.

The adaptations are ownership changes rather than feature removals:

- M5Stack's factory HAL remains the only display, touch, LVGL, PMU, codec, I2C
  and filesystem owner.
- PrintSphere and CC Island share one `hub_wifi` station; the factory Badge AP
  can temporarily take and safely return Wi-Fi ownership.
- PrintSphere appears as its own Mooncake App. Closing it hides its private UI,
  restores display/brightness state and pauses camera/preview work.
- Web Config is `http://<watch-ip>:8080`; its fallback AP page is
  `http://192.168.4.1:8080` (password `printsphere`).
- OTA accepts only a combined `StopWatch-UserDemo` image, never an upstream
  standalone PrintSphere image that would erase the other Apps.

> [!WARNING]
> Bambu Cloud login uses unofficial account APIs. On the tested CN account,
> completing an email-code login coincided with Bambu Handy and Bambu Studio
> losing their existing sessions. This is not a documented Bambu single-session
> policy, but it is enough to make **Local only** the recommended default for a
> primary account. Cloud/Hybrid mode is optional and should be enabled only if
> you accept that the official clients may require another login.

The latest formal image is 5,680,496 bytes (`0x56ad70`), leaving 610,960 bytes
(`0x95290`, 10%) in each 6 MiB OTA slot. A diagnostic build also completed six
full Launcher -> PrintSphere -> Launcher -> CC Island -> Launcher cycles on a
physical C152. Every PrintSphere opening connected and subscribed to the local
Bambu printer over MQTT. The lowest observed internal-heap watermark was 6,043
bytes; all measured task stacks retained at least 1,420 bytes, with no OOM,
allocation failure, panic, watchdog, stack overflow, or reset.

### PrintSphere first-use guide

1. Flash the **combined StopWatch Hub image** from this repository. Do not flash
   an upstream standalone PrintSphere image after installing the Hub.
2. Let the watch join the shared Wi-Fi configured in `.env`. If it cannot join,
   use PrintSphere's fallback setup AP (password `printsphere`) and open
   `http://192.168.4.1:8080`.
3. On the same LAN, open `http://<watch-ip>:8080`. If the portal is locked,
   long-press the PrintSphere display for one second and enter the displayed
   six-digit PIN.
4. Choose **Local only** for the safest normal setup, then configure the printer
   LAN address and access code. Choose Hybrid/Cloud only if you need cloud cover
   metadata or fallback and accept the official-client session warning above.
5. Confirm the browser-detected time zone and press **Apply**. It is saved as a
   device setting shared by PrintSphere and the stock watch faces. Then select
   the printer and open **PrintSphere** from the launcher.

The firmware includes 56 common IANA zones. If a browser reports an unlisted
zone, PrintSphere keeps the existing device time zone instead of forcing UTC.

The portal runs on the watch's port 8080. CC Island's bridge may also use port
8080 on the computer; these do not conflict because they are different hosts.

## CC Island

> AI coding usage and host health, living on your wrist.
>
> 把 AI 编程用量和主机状态，搬到你的手表上。

<p align="center">
  <img src="firmware/tools/cc_island.svg" width="128" alt="CC Island icon">
</p>

<p align="center">
  <img src="docs/cover.jpg" width="48%" alt="Classic two-row layout on real hardware">
  <img src="docs/screenshots/codex-page.png" width="48%" alt="Current Codex full-page layout captured from the framebuffer">
</p>

Left: the first working two-row layout on real hardware. Right: the full-page
Codex UI captured directly from the watch framebuffer before the battery footer
was added; current firmware keeps the same page and adds the footer documented
below.

CC Island turns an **M5Stack StopWatch** (round AMOLED, ESP32‑S3) into a tiny
ambient display for AI coding usage and host health. It monitors Claude Code
(orange), Codex (blue), and OpenCode (violet), including rolling usage windows,
reset countdowns, local token totals, API-equivalent value, and PC health.

It supports three providers and two transports:

- **Claude Code / Codex / OpenCode** — use the compact two-row layout, or give
  Codex and OpenCode one full page each.
- **Bluetooth LE and Wi‑Fi HTTP polling** — both optional and able to coexist.
- **Host-system monitoring** — PC name, CPU, memory, disk space and I/O, plus
  network upload/download; pages can auto-cycle or be swiped manually.
- **Watch battery footer** — level-aware battery icon and percentage on every
  CC Island page, with charging and low-battery color states read from the
  factory PMIC/HAL.

It's a hardware companion in the spirit of
[CodexIsland](https://github.com/ericjypark/codex-island) (which lives in the
MacBook notch): **local-first; provider credentials stay on the host.** A small
bridge reads the credentials your CLIs already wrote, queries the providers' own usage
endpoints, computes local statistics, and sends only the finished numbers to
the watch over Bluetooth LE or Wi-Fi HTTP.

### What CC Island needs

Unlike PrintSphere's local-printer path, CC Island has a small companion process
on a Windows, macOS, Linux, or WSL host:

- The provider CLIs remain logged in on that host; no provider credential is
  entered on the watch.
- The bridge converts provider/local-log data into a compact display payload.
- Use Wi-Fi polling for the most complete setup, or BLE NUS for low-frequency
  push. Both transports can remain compiled into the same firmware.
- Keep the bridge running for fresh readings. A temporary outage shows the
  last-good cached payload instead of clearing the watch to zero.

Installation and verification commands are in
[Run the CC Island bridge](#run-the-cc-island-bridge).

CC Island never needs Bambu credentials, and PrintSphere never needs the host's
Claude, Codex, or OpenCode credentials. The two Apps only share device-level
services.

## Project lineage

The CC Island side of this project is derived from
[alexjc-tech/cc-island](https://github.com/alexjc-tech/cc-island). Its firmware
foundation comes from M5Stack's
[M5StopWatch-UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo), while
the AI-usage companion concept and the original provider-auth recipes were
adapted from Eric Park's
[CodexIsland](https://github.com/ericjypark/codex-island). These links represent
the direct upstream, firmware foundation, and product inspiration respectively.

## CC Island setup choices

| Goal | Transport | `.env` | Host support |
| --- | --- | --- | --- |
| AI usage only | Wi‑Fi | `CC_SYSTEM_MONITOR=false` | Windows, macOS, Linux, WSL |
| AI usage + host health | Wi‑Fi | `CC_SYSTEM_MONITOR=true` | Windows, macOS, Linux, WSL |
| Low-frequency push | BLE (`bleak`) | either | Windows, macOS, Linux |

For the most complete experience, use `CC_LAYOUT=pages`, Wi‑Fi polling, and
optionally enable the System page. Use `rows` if you prefer the original dense
two-provider face. BLE and Wi‑Fi can coexist in one firmware image. Transient
provider, bridge, or Wi‑Fi failures keep the last good reading, including after
the watch restarts.

### Platform support

| Capability | Windows | macOS | Linux |
| --- | --- | --- | --- |
| Codex auth + local logs | `~/.codex` | `~/.codex` | `~/.codex` |
| Claude auth + local logs | `~/.claude/.credentials.json` | Keychain, then credentials file | `~/.claude/.credentials.json` |
| OpenCode local usage | XDG data / `opencode.db` | XDG data / `opencode.db` | XDG data / `opencode.db` |
| Host metrics | `psutil`, with PowerShell fallback | `psutil`, with native fallback | `psutil`, with `/proc` fallback |
| Wi‑Fi polling | Yes | Yes | Yes |
| BLE push | Yes | Yes | Yes (BlueZ required) |

When the bridge runs in WSL it also checks the mounted Windows profile for all
three CLIs, so an OpenCode installed on Windows is supported. Custom locations
remain explicit through `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, and `OPENCODE_DB`.

---

## What CC Island shows

Two display layouts are built in:

- **`rows`** — the compact layout: choose any two of Claude Code, Codex, and
  OpenCode for one AI page.
- **`pages`** — one full Codex page, one full OpenCode page, and optionally a
  system page. This layout has room for each window's reset time and OpenCode's
  monthly quota.

Set `CC_LAYOUT=rows|pages` before running `scripts/install_firmware.sh`.
Host monitoring is opt-in: set `CC_SYSTEM_MONITOR=true` to collect host metrics
and add the System page. In either layout the watch can show:

- **provider usage windows** — percentage, brand-colored gauge, and reset time
- **today's local token count** and **API-equivalent value**
- a **haptic buzz** when a 5‑hour window first crosses 80%
- OpenCode's **Go subscription quota** when configured (5h / weekly / monthly,
  with resets); otherwise local today/7-day usage is shown

Amounts shown as `~$` are **API-equivalent values**, not an actual bill.
Claude, Codex, and recognized OpenCode models are valued with the current public
OpenRouter price catalog. OpenCode's recorded amount remains a fallback for an
unknown model. Users on a Coding Plan, OpenCode Go, or another subscription are
not charged this amount per token.

The optional **System** page shows the bridge host's name, CPU %, memory %,
disk usage and read/write rate, plus network upload/download. Under WSL the
bridge reads the Windows host through PowerShell and falls back to the WSL VM's
metrics when interop is unavailable. Native Windows, macOS, and Linux use
`psutil`, with PowerShell, native-command, or `/proc` fallbacks respectively.
Monitoring remains opt-in because it is independent from AI usage tracking.

Swipe left/right to change pages. The **orange button** toggles auto/manual page
rotation, and the **blue button** requests an immediate refresh. Set
`CC_AUTO_SWITCH_MS=0` to start in manual mode. The footer keeps the current
`AUTO`/`MAN` state and watch battery percentage visible on every page; a trailing
`+` means external power is connected.

## Hardware

- **M5Stack StopWatch** (SKU C152): ESP32‑S3R8, 1.75" 466×466 round AMOLED
  (touch), 2 buttons + power, vibration motor, BLE 5.0, 450 mAh battery.
- Programmed on top of M5Stack's **factory firmware**
  ([M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo),
  ESP‑IDF + LVGL + Mooncake) as a new, self‑contained app — all the stock
  features (stopwatch, watch face, etc.) stay intact.

## CC Island architecture

```
  Windows / macOS / Linux (the brain)            StopWatch / "CC Island" app (the face)
  ─────────────────────────────                  ──────────────────────────────────────
  bridge/codexisland_bridge.py                   firmware/app_codex
   • Claude/Codex endpoints + local logs          • rows or per-provider pages (LVGL)
   • OpenRouter model-price catalog (cached)       • API-equivalent value (~$)
   • OpenCode SQLite + optional Go quota           • swipe + auto/manual page rotation
   • native host stats + WSL Windows integration   • optional host-system page
   • 30 s refresh + 6 h last-good fallback         • Wi-Fi polling + BLE NUS receiver
   • GET /stats ─────────HTTP (Wi‑Fi)──────────▶   • blue button → immediate refresh
   • compact JSON push ───BLE (NUS)────────────▶   • flash-backed last-good display
```

The watch is a passive BLE peripheral (the bridge connects and writes one short
JSON line per update), and can also poll the bridge over Wi‑Fi on a timer.
**Tokens, logs, API credentials, and cookies never go to the watch** — only the
computed numbers do.

## Repo layout

```
stopwatch-hub/
├── bridge/codexisland_bridge.py   # data + BLE push + HTTP server
├── pyproject.toml                 # bridge metadata + dependencies
├── uv.lock                        # reproducible Windows/macOS/Linux environment
├── firmware/
│   ├── app_codex/                 # the StopWatch app (drops into factory fw)
│   │   ├── app_codex.{h,cpp}       #   provider/system UI, gestures, page rotation
│   │   ├── app_codex_config.h      #   rows/pages, providers, system-page config
│   │   ├── ble/ble_nus.{h,cpp}     #   NimBLE Nordic UART Service (BLE transport)
│   │   ├── net/net.{h,cpp,config.h}#   Wi-Fi station + HTTP polling
│   │   └── debug/                  #   USB Serial JTAG framebuffer capture
│   ├── app_printsphere/           # PrintSphere Mooncake App lifecycle shell
│   ├── printsphere_m5/            # C152/Mooncake hardware adapter
│   ├── hub_wifi/                  # one Wi-Fi owner shared by both Apps
│   ├── hub_time/                  # SNTP + UTC RTC + device time-zone owner
│   ├── partitions.csv             # dual 6 MiB OTA + FAT layout for 16 MiB flash
│   ├── assets/                    # generated LVGL RGB565 logo bitmaps (.c)
│   └── tools/                     # SVG sources + bitmap generator; includes CC Island icon
├── vendor/PrintSphere/            # pinned full upstream Git submodule (unchanged)
├── scripts/
│   ├── install_firmware.sh        # clone V0.5 + integrate both Apps and services
│   ├── prepare_printsphere_port.py# materialize full source + asserted M5 adapters
│   └── setup_autostart.sh         # install the bridge as a login LaunchAgent
├── tools/screenshot.py            # capture the watch framebuffer as PNG
└── docs/
```

---

## Detailed setup

### Build and flash the combined firmware

Requires [ESP‑IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html).
The integration script requires Bash: use Linux or macOS directly, or WSL2 on
Windows. The CC Island bridge itself can still run natively in Windows
PowerShell after the watch is flashed.

The same `.env` contains build-time watch settings and runtime bridge settings:

| Setting | Used by | Reflash watch? | Restart bridge? |
| --- | --- | --- | --- |
| `CC_WIFI_*`, `CC_BRIDGE_*`, `CC_POLL_MS` | firmware installer | Yes | No |
| `CC_LAYOUT`, `CC_AUTO_SWITCH_MS` | firmware installer | Yes | No |
| `CC_SYSTEM_MONITOR` | firmware installer + bridge | Yes | Yes |
| `OPENCODE_GO_*`, `OPENCODE_DB` | bridge | No | Yes |
| `CODEX_HOME`, `CLAUDE_CONFIG_DIR` | bridge | No | Yes |
| `CC_PRICING_*`, `CC_CODEX_FALLBACK_MODEL` | bridge | No | Yes |

Provider secrets are not copied into the firmware. Codex and Claude reuse the
CLI credentials already present on the bridge host; OpenCode local totals come
from its read-only SQLite database.

```bash
# Run from the stopwatch-hub repository root.
git submodule update --init --recursive

# First setup only: create the gitignored local configuration.
if [ ! -f .env ]; then cp .env.example .env; fi
# edit Wi-Fi, bridge host, layout, intervals, optional system monitoring,
# and optional OpenCode Go fields

# integrate both StopWatch Hub apps into a fresh factory-firmware checkout
./scripts/install_firmware.sh           # clones into ./build-firmware

# build + flash
. ~/esp/esp-idf/export.sh
cd build-firmware
idf.py build
idf.py -p /dev/ttyACM0 flash  # Linux/WSL example; replace from the table below
```

Replace the example with the port name reported by your operating system:

| Build environment | Typical port | Note |
| --- | --- | --- |
| Linux | `/dev/ttyACM0` | Add the user to `dialout` if access is denied |
| macOS | `/dev/cu.usbmodemXXXX` | The suffix varies after reconnects |
| Windows ESP-IDF shell | `COM3` | The installer still needs Bash; WSL2 is recommended |
| WSL2 | `/dev/ttyACM0` | Attach the USB device with `usbipd` first |

For the first installation, use `idf.py flash` so the combined partition table
and application are installed together. Do not run `erase-flash` unless you
intend to wipe Wi-Fi, printer profiles, Cloud tokens, and other NVS settings.

`install_firmware.sh` bakes the `CC_*` values into the ignored
`build-firmware` checkout. Tracked source files keep placeholders only.
The Wi-Fi SSID/password are therefore present in the firmware image; provider
API credentials and OpenCode cookies remain on the bridge host.
PrintSphere also supports runtime Wi-Fi setup and stores printer/cloud settings
in its own NVS namespace. Its Web Config and low-rate state service start during
Mooncake creation and listen on port 8080. Open **CC Island** to start its BLE
and HTTP transports; opening **PrintSphere** reveals its dashboard and enables
its App-scoped display/camera work.

> [!CAUTION]
> Never publish a `StopWatch-UserDemo.bin` built with your personal `.env`: that
> image contains the configured Wi-Fi credentials and bridge address. Public
> release artifacts must be built without a personal environment file and use
> the setup AP/USB provisioning path instead. The formal device-test image
> described in this README is intentionally not tracked by Git.

After reboot, confirm the device service before configuring either App:

```bash
curl http://<watch-ip>:8080/api/health
```

Look for `"status":"ok"`, `"wifi_connected":true`, and a trustworthy system
time. The serial log also prints the watch IP as `station ready at ...`.

### Configure PrintSphere

After the watch reconnects, open `http://<watch-ip>:8080`, choose Hybrid, Cloud,
or local-only mode, configure the printer connection, and apply the detected
time zone. See the [PrintSphere first-use guide](#printsphere-first-use-guide)
for the fallback AP and portal PIN flow. This step is independent of the CC
Island bridge.

### Run the CC Island bridge

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) once,
then create the locked environment. The same command works in Windows
PowerShell, macOS, and Linux:

```console
uv sync
```

Wi‑Fi mode is recommended on every platform:

```console
uv run python bridge/codexisland_bridge.py --serve 8080
```

The bridge loads `.env` automatically. OpenCode local usage needs no extra
configuration; the optional `OPENCODE_GO_*` fields enable real Go quota windows.
`CC_SYSTEM_MONITOR=true` enables both host-stat collection and the firmware
System page; rerun the firmware install/build/flash after changing it.
Check `http://localhost:8080/` for text, `/json` for full data, or `/stats` for
the compact watch payload.

Before opening CC Island on the watch, verify the exact payload endpoint:

```bash
curl http://127.0.0.1:8080/stats
```

For Wi-Fi polling, also open `http://<bridge-lan-ip>:8080/stats` from another
device on the LAN. If localhost works but the LAN address does not, fix the host
firewall/bind/WSL networking path before debugging the watch.

BLE mode (Windows / macOS / Linux through `bleak`):

```console
uv run python bridge/codexisland_bridge.py --ble 5
```

The bridge finds the watch (named `CC Island`), connects, and starts pushing.
macOS prompts for Bluetooth permission; Linux needs a working BlueZ/D-Bus
session. The bundled login-service installer is currently macOS-specific:

```bash
./scripts/setup_autostart.sh            # macOS, default: every 5 min
```

Use `--json` or no arguments to inspect provider data without starting a
transport.

---

## Using CC Island

- **Auto‑refresh (Wi‑Fi)**: the watch polls the bridge every `net_config.h::poll_ms`
  (template default 10 s; `.env.example` uses 5 s). Provider API/log data is
  cached for 30 s; when enabled, host stats refresh every 4 s. A 5 s device
  poll therefore does not re-query providers every time.
- **Offline cache**: a provider refresh error keeps its last good bridge value
  for up to 6 hours. The watch also keeps the latest valid Codex payload in RAM
  and persists it at most once every 5 minutes, so reopening the app or rebooting
  while the bridge is unreachable shows the previous reading instead of zeros.
- **Auto‑refresh (BLE)**: every N minutes (default 5; Anthropic rate‑limits the
  usage endpoint, so don't go below a few minutes).
- **Page switch**: swipe left/right, or use automatic rotation (source
  fallback: 5 s). The **orange button** toggles `AUTO` (timer-based cycling) /
  `MAN` (stay on the current page until you swipe);
  `.env.example` sets `CC_AUTO_SWITCH_MS=0`, so generated firmware starts in
  manual mode unless you change it.
- **Manual refresh**: press the **blue button** — the watch buzzes and asks
  the bridge to push immediately (throttled to once / 5 s).
- **Exit the app**: hold **both buttons** (the factory firmware's "go home").

## Customizing CC Island

- **Local configuration** — copy `.env.example` to `.env`. `CC_WIFI_*`,
  `CC_BRIDGE_*`, and `CC_POLL_MS` configure Wi-Fi polling;
  `CC_LAYOUT=rows|pages` and `CC_AUTO_SWITCH_MS` configure navigation;
  `CC_SYSTEM_MONITOR=true|false` controls both host-stat collection and the
  System page. `.env` and `build-firmware/` are ignored by Git.
- **Rows providers / system page** — `firmware/app_codex/app_codex_config.h`
  (`kTopProvider` / `kBottomProvider`: `"c"` Claude, `"x"` Codex, `"o"`
  OpenCode; `kShowSystemPage`). The full-page layout currently creates Codex
  and OpenCode provider pages.
- **Wi-Fi template defaults** — `firmware/app_codex/net/net_config.h`.
- **Colors / alert threshold / fonts** — `firmware/app_codex/app_codex.cpp`
  (`kClaudeColor`, `kCodexColor`, `kOpencodeColor`, `kAlertThreshold`).
- **Go quota config** — env vars `OPENCODE_GO_WORKSPACE_ID` /
  `OPENCODE_GO_AUTH_COOKIE`, or `--go-workspace` / `--go-cookie`.
- **Refresh interval (BLE)** — argument to the bridge (`--ble <minutes>`), or edit the
  LaunchAgent.
- **Real framebuffer screenshot** — connect USB, then run:

  ```console
  uv run --with pyserial --with pillow python tools/screenshot.py out.png --port /dev/ttyACM0
  ```

  Developers can add `--advance 1` (or `-1`) to switch pages before capture.
- **Launcher icon / provider logos** — `cc_island.svg` is CC Island's independent
  launcher mark; the other SVGs identify individual providers. Regenerate all
  firmware bitmaps with:
  ```bash
  uv run --with svglib --with pillow --with reportlab --with rlpycairo \
    python firmware/tools/gen_icons.py       # rewrites firmware/assets/*.c
  python firmware/tools/gen_printsphere_icon.py
  ```
- **Pricing** — the bridge refreshes OpenRouter's public
  [`/api/v1/models`](https://openrouter.ai/api/v1/models) catalog every six
  hours and keeps a last-good disk cache plus a small embedded offline fallback.
  Set `CC_PRICING_REFRESH_HOURS` or `CC_PRICING_CACHE` to override those defaults;
  `CC_CODEX_FALLBACK_MODEL` controls how the hidden `codex-auto-review` model is
  valued (default `gpt-5.6-sol`). OpenCode router/subscription provider IDs are
  matched to an unambiguous public model ID when their publisher name differs.

## How CC Island works (data sources)

- **Codex**: `GET https://chatgpt.com/backend-api/wham/usage` with the
  `access_token` from `CODEX_HOME/auth.json` (normally `~/.codex/auth.json`).
  Today's cost comes from its session JSONL files. In WSL the Windows profile
  is also auto-detected.
- **Claude**: `GET https://api.anthropic.com/api/oauth/usage` with a Claude Code
  token (`CLAUDE_CODE_OAUTH_TOKEN` → macOS Keychain →
  `CLAUDE_CONFIG_DIR/.credentials.json` → OAuth refresh) plus the CLI
  `User-Agent` and `anthropic-beta` header. Linux and Windows therefore reuse
  the login already written by Claude Code.
- **OpenCode**: read-only SQLite query of its official XDG data directory,
  normally `~/.local/share/opencode/opencode.db` on all three platforms.
  Stable, beta, and development database names are auto-detected. Today's and
  7-day values use each assistant message's timestamp and token counters, so a
  session continued across midnight remains accurate. Duplicate subagent call
  fingerprints are counted once. Known models are repriced through OpenRouter
  to show API-equivalent value even when a Coding Plan records zero cost;
  unknown models and older schemas fall back to OpenCode's recorded amount.
  `/json` retains that amount as `actual_t` / `actual_d` for diagnostics.
  Override the path with `OPENCODE_DB` or `--db`.
- **OpenCode Go quota** (optional): set `OPENCODE_GO_WORKSPACE_ID` and
  `OPENCODE_GO_AUTH_COOKIE` (or `--go-workspace` / `--go-cookie`) to also show
  the real subscription windows. OpenCode has no public usage API, so this
  scrapes `https://opencode.ai/workspace/<id>/go` with your browser's `auth`
  cookie (the community approach). Results are cached for five minutes. The
  cookie starts with `Fe26.2**` and expires periodically — re-export it from
  **F12 → Application → Cookies → https://opencode.ai → `auth`** when auth fails.
- **System** (optional): when `CC_SYSTEM_MONITOR=true`, reads CPU / memory /
  disk / network from native Windows, macOS, or Linux; WSL targets the Windows
  host first through PowerShell. `psutil` supplies full cross-platform disk and
  network rates, while Windows PowerShell, macOS native commands, and Linux
  `/proc` remain fallbacks. When false, the bridge neither samples these metrics
  nor includes `sys`.
- **Cost**: parses `~/.claude/projects/**/*.jsonl`,
  `~/.codex/sessions/**/rollout-*.jsonl`, and OpenCode's local database for
  token usage, then prices recognized models from OpenRouter's frequently
  updated public catalog. Only that public catalog is downloaded; local
  credentials, prompts, and usage never leave the host.
  The displayed `~$` is an API-equivalent value, not the user's Coding Plan or
  subscription charge. Exact model IDs are preferred, then dated/provider
  aliases and the offline fallback. Unknown models still add to the token total
  and are reported under `/json` pricing diagnostics; OpenCode can retain its
  recorded amount as a fallback. The token total counts non-cached input,
  cached input, cache writes, and output once each. Codex reasoning is already
  part of output; OpenCode's separately reported reasoning is added once at the
  output rate.

The original provider auth and local-log recipes were adapted from
[CodexIsland](https://github.com/ericjypark/codex-island); the firmware UI,
OpenCode, Wi-Fi polling, system monitoring, and navigation live in this project.

## Contributing

Pull requests are welcome, especially for additional coding providers and
platform integrations. A new provider should keep credentials on the host and,
where applicable, include its bridge collector, compact watch payload,
firmware row/page, configuration, tests, and English/Chinese documentation.
Please also distinguish real subscription quotas from locally calculated token
or API-equivalent cost estimates.

## Troubleshooting

- **Wi‑Fi mode: watch shows nothing** — open the CC Island app, confirm the
  bridge is reachable from the watch's network (`curl http://<host>:<port>/stats`
  from a phone on the same AP); see the WSL networking section below.
- **Bridge can't find the watch** — open the CC Island app on the watch (BLE
  only advertises after the first app open per boot); check Bluetooth permission
  on Windows/macOS or BlueZ/D-Bus access on Linux.
- **`SSL: CERTIFICATE_VERIFY_FAILED`** — rerun `uv sync`; the locked environment
  includes `certifi`, and the bridge prefers its CA bundle.
- **Firmware build: `nimble/nimble_port.h: No such file`** — BLE isn't enabled;
  delete the **root** `sdkconfig` (not `build/sdkconfig`) and `idf.py reconfigure`.
- **Linker: `undefined reference to AppCodex`** after adding files — `idf.py
  reconfigure` (CMake re‑globs sources).
- **`incompatible architecture (arm64 vs x86_64)`** on Apple Silicon — an Intel
  `ninja` is dragging the toolchain to x86_64; `brew install ninja` and put
  `/opt/homebrew/bin` first on `PATH`.
- **Go quota auth errors** — the `auth` cookie expired; re‑export it.
- **A CLI works but the bridge says auth/database missing** — the CLI and bridge
  are using different homes (common with WSL, services, `sudo`, or custom XDG
  paths). Set `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, or `OPENCODE_DB` explicitly.
- **Native Windows: the watch cannot reach Wi-Fi mode** — allow TCP port 8080
  through Windows Defender Firewall (run PowerShell as administrator):

  ```powershell
  netsh advfirewall firewall add rule name="cc-island" dir=in action=allow protocol=TCP localport=8080
  ```
- **Codex shows `network unreachable` / `network timeout`** — this is a bridge
  transport problem, not expired Codex auth. Check the bridge process's proxy
  and DNS environment. In particular, `sudo` often removes `HTTP_PROXY`,
  `HTTPS_PROXY`, and `ALL_PROXY`; configure them in the service unit or run the
  bridge as your normal user. Older builds displayed the same condition as the
  misleading `http 0`.

### WSL2 networking (Wi‑Fi mode)

WSL2 uses NAT by default, so the watch can't reach a server bound inside WSL
directly. Either:

- **Mirrored networking** (Windows 11 22H2+): add to `%UserProfile%\.wslconfig`
  ```
  [wsl2]
  networkingMode=mirrored
  ```
  then the bridge's port is reachable on the Windows host IP.
- **Port proxy** (works on any Windows, admin PowerShell):
  ```powershell
  netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=8080 connectaddress=<wsl-ip>
  netsh advfirewall firewall add rule name="cc-island" dir=in action=allow protocol=TCP localport=8080
  ```
  Get `<wsl-ip>` with `hostname -I` inside WSL, and point `net_config.h`'s
  `host` at the **Windows host IP**.

## Credits & trademarks

- Maintained fork of
  [alexjc-tech/cc-island](https://github.com/alexjc-tech/cc-island) (MIT).
- Built on M5Stack's [M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo) (MIT).
- Inspired by [CodexIsland](https://github.com/ericjypark/codex-island) by Eric Park.
- BLE legacy-advertising packet fix based on
  [PR #1](https://github.com/alexjc-tech/cc-island/pull/1) by
  [@xiaoyuanzi1230](https://github.com/xiaoyuanzi1230).
- The independent CC Island launcher icon combines a three-provider ring with a
  monitoring pulse. Provider-row logo bitmaps are derived from the
  **Anthropic/Claude** and **OpenAI** brand marks (via
  [simple‑icons](https://github.com/simple-icons/simple-icons) and
  [lobe‑icons](https://github.com/lobehub/lobe-icons)). Those marks are trademarks
  of their respective owners and are used here only to identify each service.
  This project is not affiliated with or endorsed by Anthropic or OpenAI.

## License

This is a mixed-license repository. CC Island and the original integration code
are MIT; PrintSphere-derived port files use FNCL v1.1 and are non-commercial
unless separately licensed. See [LICENSE](LICENSE), [NOTICE.md](NOTICE.md), and
the per-file SPDX identifiers.
