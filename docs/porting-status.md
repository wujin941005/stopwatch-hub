# PrintSphere to M5Stack StopWatch port status

Pinned source: PrintSphere v1.6.2 at
`ed071d11dd09c2c93abdba62d8458e4b592f79d0`.

The full upstream `main/include` and `main/src` trees are materialized from the
Git submodule. Hardware-global calls are then replaced by asserted adapters;
the upstream submodule itself remains unchanged.

| Area | Integration status | Validation status |
| --- | --- | --- |
| LAN MQTT, V1/V2 parsing and commands | Integrated | ESP-IDF build passed; device pending |
| Cloud REST/MQTT, login and 2FA | Integrated | ESP-IDF build passed; live account pending |
| Hybrid resolver and multi-printer profiles | Integrated | ESP-IDF build passed; device pending |
| Full LVGL dashboard, AMS, errors and controls | Integrated as `PrintSphere` App | Build passed; touch/UI device pass pending |
| Cloud cover preview and local JPEG camera | Integrated | Pauses outside App; live printer pending |
| Web Config, PIN, Wi-Fi scan and fallback AP | Integrated on port 8080 | Build passed; browser/device pending |
| Time zone and SNTP | Integrated | Connect transition restored; device pending |
| 0/90/180/270 display + touch rotation | App-scoped display lease | Build passed; all orientations pending |
| Battery, brightness and power policy | M5Stack HAL adapter | Build passed; battery test pending |
| Event sounds and custom WAV | M5Stack HAL + shared FAT | Build passed; speaker/upload pending |
| USB Improv provisioning | Integrated; URL reports port 8080 | Build passed; host/device pending |
| OTA upload and OTA URL | Combined firmware only | Project-name guards compiled; device pending |
| Shared Wi-Fi with CC Island and Badge AP | One `hub_wifi` owner | Build passed; coexistence soak pending |

## Validation snapshot (2026-08-15)

- Factory base: M5Stack `M5StopWatch-UserDemo` V0.5 commit
  `6b4aa125288b6fe9dca661f10159f6e1e5ee785c`.
- ESP-IDF v5.5.4 full build with the complete PrintSphere source: passed.
- Combined `StopWatch-UserDemo.bin`: 5,718,240 bytes (`0x5740e0`).
- Each OTA app slot: 6,291,456 bytes; remaining: 573,216 bytes
  (`0x8bf20`, 9%).
- Linked DIRAM: 187,427 / 341,760 bytes; 154,333 bytes remain statically.
- Python tests: 22 passed, including full source inventory, adapter ownership,
  lifecycle/OTA policy and materialization idempotence.
- Host C++17 state/status smoke test: passed with
  `-Wall -Wextra -Werror`.
- Full installer rerun: byte-identical generated trees and factory diff.

## Remaining acceptance work

Compilation proves that the complete feature code fits and links; it does not
prove radio, heap or peripheral behavior on a physical watch. Before calling a
release device-validated, test Wi-Fi + NimBLE + MQTT/TLS coexistence, local and
cloud printers including 2FA, JPEG camera/preview heap peaks, all rotations,
custom WAV playback, USB Improv, Badge AP handoff, reconnects, battery behavior,
and both OTA paths on a C152.
