# CC Island

> Your Claude Code & Codex usage limits, living on your wrist.
>
> 把 Claude Code 和 Codex 的用量额度，搬到你的手表上。

![CC Island running on an M5Stack StopWatch](docs/cover.jpg)

This is the first working CC Island face on real hardware. The photo shows
Claude Code and Codex usage side by side: the large percentage is the current
5-hour window, the smaller `7d` percentage is the weekly window, `reset` is the
time until the current window refreshes, and the bottom numbers show today's
estimated spend and token volume from local session logs.

CC Island turns an **M5Stack StopWatch** (round AMOLED, ESP32‑S3) into a tiny
ambient display for your AI coding usage. One screen shows both providers at a
glance — Claude Code (orange) on top, Codex (blue) below — with each one's
5‑hour and weekly windows, reset countdown, and today's estimated cost/tokens.

It's a hardware companion in the spirit of
[CodexIsland](https://github.com/ericjypark/codex-island) (which lives in the
MacBook notch): **local‑first, no secrets on the device.** A small Mac‑side
bridge reads the credentials your CLIs already wrote, queries the providers'
own usage endpoints, computes cost from local session logs, and pushes the
finished numbers to the watch over Bluetooth LE.

---

## What it shows / 显示什么

For each of **Claude Code** and **Codex**, on a single round screen:

- **5‑hour window** utilization — big % + a brand‑colored gauge bar
- **7‑day window** utilization
- **reset countdown** for the 5‑hour window
- **today's cost** (USD‑equivalent) and **token count** from local logs
- a **haptic buzz** when a 5‑hour window first crosses 80%

Press the **blue button (G1)** to refresh on demand; otherwise it auto‑refreshes
on a timer.

## Hardware

- **M5Stack StopWatch** (SKU C152): ESP32‑S3R8, 1.75" 466×466 round AMOLED
  (touch), 2 buttons + power, vibration motor, BLE 5.0, 450 mAh battery.
- Programmed on top of M5Stack's **factory firmware**
  ([M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo),
  ESP‑IDF + LVGL + Mooncake) as a new, self‑contained app — all the stock
  features (stopwatch, watch face, etc.) stay intact.

## Architecture

```
  Mac (the brain)                              StopWatch / "CC Island" app (the face)
  ─────────────────────────────               ──────────────────────────────────────
  bridge/codexisland_bridge.py                 firmware/app_codex
   • read ~/.codex/auth.json                    • NimBLE Nordic-UART-Service server
   • read Keychain "Claude Code-credentials"    • parse JSON, draw two rows (LVGL arcs/bars)
   • call providers' usage endpoints            • blue button (G1) → request refresh
   • cost from ~/.claude & ~/.codex logs        • buzz on threshold crossing
   • push compact JSON  ──────BLE (NUS)──────▶  • shows official Anthropic / OpenAI logos
```

The watch is a passive BLE peripheral. The Mac is the BLE central that connects
and writes one short JSON line per update. **No tokens or logs ever leave the
Mac** — only the computed numbers do.

## Repo layout

```
cc-island/
├── bridge/codexisland_bridge.py   # Mac-side data + BLE push (pure Python)
├── firmware/
│   ├── app_codex/                 # the StopWatch app (drops into factory fw)
│   │   ├── app_codex.{h,cpp}       #   UI + lifecycle + button handling
│   │   └── ble/ble_nus.{h,cpp}     #   NimBLE Nordic UART Service
│   ├── assets/                    # generated LVGL RGB565 logo bitmaps (.c)
│   └── tools/gen_icons.py         # regenerate the logo bitmaps from SVG
├── scripts/
│   ├── install_firmware.sh        # clone factory fw + integrate app_codex
│   └── setup_autostart.sh         # install the bridge as a login LaunchAgent
└── docs/
```

---

## Quick start

### 1. Flash the firmware

Requires [ESP‑IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html).

```bash
# integrate the app into a fresh factory-firmware checkout
./scripts/install_firmware.sh           # clones into ./build-firmware

# build + flash
. ~/esp/esp-idf/export.sh
cd build-firmware
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash
```

On the watch, open the **CC Island** app once after boot — this starts BLE
advertising.

### 2. Run the Mac bridge

```bash
# one-time: install as a background service that starts at login
./scripts/setup_autostart.sh            # default: refresh every 5 min
```

The first run triggers a macOS **Bluetooth permission** prompt — click **Allow**.
The bridge finds the watch (named `CC Island`), connects, and starts pushing.

> Prefer to run it by hand? `python3 bridge/codexisland_bridge.py --ble 5`
> (or `--json` / no args to just print the numbers).

---

## Using it

- **Auto‑refresh**: every N minutes (default 5; Anthropic rate‑limits the usage
  endpoint, so don't go below a few minutes).
- **Manual refresh**: press the **blue button (G1)** — the watch buzzes and asks
  the Mac to push immediately (throttled to once / 5 s).
- **Exit the app**: hold **both buttons** (the factory firmware's "go home").

## Customizing

- **Colors / alert threshold / fonts** — `firmware/app_codex/app_codex.cpp`
  (`kClaudeColor`, `kCodexColor`, `kAlertThreshold`).
- **Refresh interval** — argument to the bridge (`--ble <minutes>`), or edit the
  LaunchAgent.
- **Logos** — drop new SVGs in `firmware/tools/`, edit `gen_icons.py`, then:
  ```bash
  python3 -m pip install --user svglib pillow
  python3 firmware/tools/gen_icons.py        # rewrites firmware/assets/*.c
  ```
- **Pricing table** — `_PRICING` in `bridge/codexisland_bridge.py` (per‑million
  USD rates, mirrors LiteLLM / ccusage).

## How it works (data sources)

- **Codex**: `GET https://chatgpt.com/backend-api/wham/usage` with the
  `access_token` from `~/.codex/auth.json`.
- **Claude**: `GET https://api.anthropic.com/api/oauth/usage` with a Claude Code
  token (env → Keychain `Claude Code-credentials` → OAuth refresh) plus the CLI
  `User-Agent` and `anthropic-beta` header.
- **Cost**: parses `~/.claude/projects/**/*.jsonl` and
  `~/.codex/sessions/**/rollout-*.jsonl` for token usage and prices each turn
  from an embedded table — the same data `ccusage` reads.

All recipes mirror [CodexIsland](https://github.com/ericjypark/codex-island).

## Troubleshooting

- **Bridge can't find the watch** — open the CC Island app on the watch (BLE
  only advertises after the first app open per boot); make sure the bridge has
  macOS Bluetooth permission.
- **`SSL: CERTIFICATE_VERIFY_FAILED`** — the python.org Python ships no CA store;
  `pip install --user certifi` (the bridge already prefers it).
- **Firmware build: `nimble/nimble_port.h: No such file`** — BLE isn't enabled;
  delete the **root** `sdkconfig` (not `build/sdkconfig`) and `idf.py reconfigure`.
- **Linker: `undefined reference to AppCodex`** after adding files — `idf.py
  reconfigure` (CMake re‑globs sources).
- **`incompatible architecture (arm64 vs x86_64)`** on Apple Silicon — an Intel
  `ninja` is dragging the toolchain to x86_64; `brew install ninja` and put
  `/opt/homebrew/bin` first on `PATH`.

## Credits & trademarks

- Built on M5Stack's [M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo) (MIT).
- Inspired by [CodexIsland](https://github.com/ericjypark/codex-island) by Eric Park.
- Logo bitmaps are derived from the **Anthropic/Claude** and **OpenAI** brand
  marks (via [simple‑icons](https://github.com/simple-icons/simple-icons) and
  [lobe‑icons](https://github.com/lobehub/lobe-icons)). Those marks are
  trademarks of their respective owners and are used here only to identify each
  service. This project is not affiliated with or endorsed by Anthropic or OpenAI.

## License

MIT — see [LICENSE](LICENSE). (Trademark notice above applies to the brand logos.)
