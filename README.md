# CC Island

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

Left: the first working two-row layout on real hardware. Right: the current
full-page Codex UI, captured directly from the watch framebuffer.

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

It's a hardware companion in the spirit of
[CodexIsland](https://github.com/ericjypark/codex-island) (which lives in the
MacBook notch): **local-first; provider credentials stay on the host.** A small
bridge reads the credentials your CLIs already wrote, queries the providers' own usage
endpoints, computes local statistics, and sends only the finished numbers to
the watch over Bluetooth LE or Wi‑Fi HTTP.

## Project lineage

This maintained fork is based on
[alexjc-tech/cc-island](https://github.com/alexjc-tech/cc-island). Its firmware
foundation comes from M5Stack's
[M5StopWatch-UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo), while
the AI-usage companion concept and the original provider-auth recipes were
adapted from Eric Park's
[CodexIsland](https://github.com/ericjypark/codex-island). These links represent
the direct upstream, firmware foundation, and product inspiration respectively.

## Pick a setup

| Goal | Transport | `.env` | Host support |
| --- | --- | --- | --- |
| AI usage only | Wi‑Fi | `CC_SYSTEM_MONITOR=false` | Windows, macOS, Linux, WSL |
| AI usage + host health | Wi‑Fi | `CC_SYSTEM_MONITOR=true` | Windows, macOS, Linux, WSL |
| Low-frequency push | BLE (`bleak`) | either | Windows, macOS, Linux |

For the most complete experience, use `CC_LAYOUT=pages`, Wi‑Fi polling, and
optionally enable the System page. Use `rows` if you prefer the original dense
two-provider face. BLE and Wi‑Fi can coexist in one firmware image.

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

## What it shows / 显示什么

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
Claude/Codex logs are valued with the current public OpenRouter price catalog;
OpenCode uses the per-message cost it records itself. Users on a Coding Plan,
OpenCode Go, or another subscription are not charged this amount per token.

The optional **System** page shows the bridge host's name, CPU %, memory %,
disk usage and read/write rate, plus network upload/download. Under WSL the
bridge reads the Windows host through PowerShell and falls back to the WSL VM's
metrics when interop is unavailable. Native Windows, macOS, and Linux use
`psutil`, with PowerShell, native-command, or `/proc` fallbacks respectively.
Monitoring remains opt-in because it is independent from AI usage tracking.

Swipe left/right to change pages. The **orange button** toggles auto/manual page
rotation, and the **blue button** requests an immediate refresh. Set
`CC_AUTO_SWITCH_MS=0` to start in manual mode.

## Hardware

- **M5Stack StopWatch** (SKU C152): ESP32‑S3R8, 1.75" 466×466 round AMOLED
  (touch), 2 buttons + power, vibration motor, BLE 5.0, 450 mAh battery.
- Programmed on top of M5Stack's **factory firmware**
  ([M5StopWatch‑UserDemo](https://github.com/m5stack/M5StopWatch-UserDemo),
  ESP‑IDF + LVGL + Mooncake) as a new, self‑contained app — all the stock
  features (stopwatch, watch face, etc.) stay intact.

## Architecture

```
  Windows / macOS / Linux (the brain)            StopWatch / "CC Island" app (the face)
  ─────────────────────────────                  ──────────────────────────────────────
  bridge/codexisland_bridge.py                   firmware/app_codex
   • Claude/Codex endpoints + local logs          • rows or per-provider pages (LVGL)
   • OpenRouter model-price catalog (cached)       • API-equivalent value (~$)
   • OpenCode SQLite + optional Go quota           • swipe + auto/manual page rotation
   • native host stats + WSL Windows integration   • optional host-system page
   • 30 s provider cache / 4 s system refresh      • Wi-Fi polling + BLE NUS receiver
   • GET /stats ─────────HTTP (Wi‑Fi)──────────▶   • blue button → immediate refresh
   • compact JSON push ───BLE (NUS)────────────▶   • threshold-crossing vibration
```

The watch is a passive BLE peripheral (the bridge connects and writes one short
JSON line per update), and can also poll the bridge over Wi‑Fi on a timer.
**Tokens, logs, API credentials, and cookies never go to the watch** — only the
computed numbers do.

## Repo layout

```
cc-island/
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
│   ├── assets/                    # generated LVGL RGB565 logo bitmaps (.c)
│   └── tools/                     # SVG sources + bitmap generator; includes CC Island icon
├── scripts/
│   ├── install_firmware.sh        # clone factory fw + integrate app_codex
│   └── setup_autostart.sh         # install the bridge as a login LaunchAgent
├── tools/screenshot.py            # capture the watch framebuffer as PNG
└── docs/
```

---

## Quick start

### 1. Flash the firmware

Requires [ESP‑IDF v5.5.4](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/index.html).

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
# local settings and secrets (gitignored — never commit this file)
cp .env.example .env
# edit Wi-Fi, bridge host, layout, intervals, optional system monitoring,
# and optional OpenCode Go fields

# integrate the app into a fresh factory-firmware checkout
./scripts/install_firmware.sh           # clones into ./build-firmware

# build + flash
. ~/esp/esp-idf/export.sh
cd build-firmware
idf.py build
idf.py -p /dev/cu.usbmodemXXXX flash
```

`install_firmware.sh` bakes the `CC_*` values into the ignored
`build-firmware` checkout. Tracked source files keep placeholders only.
The Wi-Fi SSID/password are therefore present in the firmware image; provider
API credentials and OpenCode cookies remain on the bridge host.
On the watch, open the **CC Island** app once after boot to start its transports.

### 2. Run the bridge

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

## Using it

- **Auto‑refresh (Wi‑Fi)**: the watch polls the bridge every `net_config.h::poll_ms`
  (template default 10 s; `.env.example` uses 5 s). Provider API/log data is
  cached for 30 s; when enabled, host stats refresh every 4 s. A 5 s device
  poll therefore does not re-query providers every time.
- **Auto‑refresh (BLE)**: every N minutes (default 5; Anthropic rate‑limits the
  usage endpoint, so don't go below a few minutes).
- **Page switch**: swipe left/right, or use automatic rotation (source
  fallback: 5 s). The **orange button** toggles `AUTO` / `MAN`;
  `.env.example` sets `CC_AUTO_SWITCH_MS=0`, so generated firmware starts in
  manual mode unless you change it.
- **Manual refresh**: press the **blue button** — the watch buzzes and asks
  the bridge to push immediately (throttled to once / 5 s).
- **Exit the app**: hold **both buttons** (the factory firmware's "go home").

## Customizing

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
  ```
- **Pricing** — the bridge refreshes OpenRouter's public
  [`/api/v1/models`](https://openrouter.ai/api/v1/models) catalog every six
  hours and keeps a last-good disk cache plus a small embedded offline fallback.
  Set `CC_PRICING_REFRESH_HOURS` or `CC_PRICING_CACHE` to override those defaults;
  `CC_CODEX_FALLBACK_MODEL` controls how the hidden `codex-auto-review` model is
  valued (default `gpt-5.6-sol`).

## How it works (data sources)

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
  7-day values sum each
  assistant message's own `cost` and token counters by message time, so a
  session continued across midnight remains accurate. Override the path with
  `OPENCODE_DB` or `--db`; older schemas fall back to session aggregates. This
  recorded cost is used directly rather than repricing OpenCode tokens through
  the OpenRouter catalog.
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
- **Cost**: parses `~/.claude/projects/**/*.jsonl` and
  `~/.codex/sessions/**/rollout-*.jsonl` for token usage and prices each turn
  from OpenRouter's frequently updated public catalog. Only that public catalog
  is downloaded; local credentials, prompts, and usage never leave the host.
  The displayed `~$` is an API-equivalent value, not the user's Coding Plan or
  subscription charge. Exact model IDs are preferred, then dated/provider
  aliases and the offline fallback. Unknown models still add to the token total
  and are reported under `/json` pricing diagnostics. The token total counts
  non-cached input, cached input, cache writes, and output once each; Codex
  reasoning tokens are already part of output and are not added again.

The original provider auth and local-log recipes were adapted from
[CodexIsland](https://github.com/ericjypark/codex-island); the firmware UI,
OpenCode, Wi-Fi polling, system monitoring, and navigation live in this project.

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

MIT — see [LICENSE](LICENSE). (Trademark notice above applies to the brand logos.)
