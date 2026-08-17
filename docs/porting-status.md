# PrintSphere to M5Stack StopWatch port status

Pinned source: PrintSphere v1.6.2 at
`ed071d11dd09c2c93abdba62d8458e4b592f79d0`.

The full upstream `main/include` and `main/src` trees are materialized from the
Git submodule. Hardware-global calls are then replaced by asserted adapters;
the upstream submodule itself remains unchanged.

| Area | Integration status | Validation status |
| --- | --- | --- |
| LAN MQTT, V1/V2 parsing and commands | Integrated | Live printer connected, subscribed and delivered telemetry in all six device cycles; destructive controls pending |
| Cloud REST/MQTT, login and 2FA | Integrated | CN email-code session completed on device; Cloud MQTT pending, and official-client session compatibility is unsafe |
| Hybrid resolver and multi-printer profiles | Integrated | Hybrid handoff to the selected local printer passed on device; multi-printer switching pending |
| Full LVGL dashboard, AMS, errors and controls | Integrated as `PrintSphere` App | App open/close and live telemetry passed on device; destructive controls pending |
| Cloud cover preview and local JPEG camera | Integrated | Pauses outside App; live camera path pending |
| Web Config, PIN, Wi-Fi scan and fallback AP | Integrated on port 8080 | LAN browser flow passed; PIN/AP edge cases still need a full matrix |
| Time zone and SNTP | Shared device service + PrintSphere settings | SNTP, UTC RTC persistence, `Asia/Shanghai` -> `CST-8`, and stock-face sharing passed on device |
| 0/90/180/270 display + touch rotation | App-scoped display lease | Build passed; all orientations pending |
| Battery, brightness and power policy | M5Stack HAL adapter | Build passed; battery test pending |
| Event sounds and custom WAV | M5Stack HAL + shared FAT | Build passed; speaker/upload pending |
| USB Improv provisioning | Integrated; URL reports port 8080 | Build passed; host/device pending |
| OTA upload and OTA URL | Combined firmware only | Project-name guards compiled; device pending |
| Shared Wi-Fi with CC Island and Badge AP | One `hub_wifi` owner | CC Island + PrintSphere reconnect and runtime passed; Badge AP handoff matrix pending |

## Validation snapshot (2026-08-17)

- Factory base: M5Stack `M5StopWatch-UserDemo` V0.5 commit
  `6b4aa125288b6fe9dca661f10159f6e1e5ee785c`.
- ESP-IDF v5.5.4 full build with the complete PrintSphere source: passed.
- Formal combined `StopWatch-UserDemo.bin`: 5,680,496 bytes (`0x56ad70`).
- Each OTA app slot: 6,291,456 bytes; remaining: 610,960 bytes
  (`0x95290`, 10%).
- Linked DIRAM: 178,055 / 341,760 bytes; 163,705 bytes remain statically.
- Python tests: 34 passed, including full source inventory, adapter ownership,
  lifecycle/OTA policy and materialization idempotence.
- Host C++17 state/status smoke test: passed with
  `-Wall -Wextra -Werror`.
- Full installer rerun: byte-identical generated trees and factory diff.
- Physical C152 flash and boot: passed with CC Island and PrintSphere installed
  beside the stock Apps. A diagnostic build completed six full Launcher ->
  PrintSphere -> Launcher -> CC Island -> Launcher cycles without a reset.
- CC Island's level-aware battery icon, percentage, charging state, and footer
  spacing passed physical-display inspection.
- Every PrintSphere opening connected and subscribed to the selected local
  printer over TLS MQTT port 8883; telemetry was received and parsed.
- A CN email-code Cloud login completed and returned the account printer list,
  but the same login coincided with Bambu Handy and Bambu Studio losing their
  existing sessions. Local-only mode is therefore the recommended default.
- Shared Wi-Fi, Web Config, SNTP, RX8130 UTC persistence, and device-level time
  zone persistence: passed. The device remained online past the 60-second
  regression window without a panic; an earlier coexistence run passed 250 s.
- The six-cycle run observed a 6,043-byte historical minimum internal heap and
  a stable 8.7--10 KiB largest internal block. It reported no OOM/allocation
  failure, panic/abort, watchdog, stack overflow, or reset.
- Minimum sampled task-stack margins were: NimBLE host 1,420 bytes, main 1,756,
  ESP-MQTT 2,092, Bambu Cloud 2,228, system event 2,412, CC Island network
  2,572, LVGL 2,564, PrintSphere 2,708, printer client 3,012, and USB screenshot
  3,160.
- Internal SRAM remains reserved for Wi-Fi, NimBLE, AMOLED DMA, and
  Flash-cache-sensitive work. The CC Island network and screenshot task stacks,
  screenshot scratch buffers, LVGL objects, and eligible MQTT stacks/buffers
  use PSRAM. The LVGL worker keeps a measured 12 KiB internal stack.

## Remaining acceptance work

The combined firmware now has a physical-watch boot, networking, time-service,
Web Config, local-printer MQTT, email-code Cloud session, and six-cycle
coexistence pass. Before calling every PrintSphere feature device-validated,
still test Cloud MQTT without relying on primary-account session coexistence,
destructive printer commands and AMS/error cases,
JPEG camera/preview heap peaks,
all rotations, custom WAV playback, USB Improv, Badge AP handoff, longer
Wi-Fi + NimBLE + MQTT/TLS soak runs, battery behavior, and both OTA paths.
