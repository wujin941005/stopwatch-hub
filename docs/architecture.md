# StopWatch Hub architecture

StopWatch Hub is one ESP-IDF firmware image with multiple Mooncake Apps. It is
not a boot selector and does not embed two standalone firmware images.

## Ownership

| Resource | Sole owner | Consumers |
| --- | --- | --- |
| Display, touch and LVGL task | M5Stack factory HAL | Official Apps, CC Island, PrintSphere |
| PMU, battery, vibration, audio and I2C | M5Stack factory HAL | All Apps through HAL APIs |
| Mooncake loop | Factory `main.cpp` | All installed Apps |
| Wi-Fi driver, event loop, STA/AP netifs | `hub_wifi` | CC Island, PrintSphere, Badge AP handoff |
| AI bridge configuration | CC Island build config | CC Island only |
| Printer/cloud configuration | PrintSphere NVS namespace | PrintSphere; Wi-Fi handed to `hub_wifi` |
| Uploaded PrintSphere sounds | `/spiflash/printsphere` | PrintSphere through factory FAT mount |
| OTA slots and image policy | Combined hub firmware | PrintSphere Web Config OTA endpoints |

No App may initialize board hardware or create a second global network/display
stack. PrintSphere's upstream submodule stays unchanged; the installer copies
the complete business source and applies asserted platform adapters to the
disposable factory-firmware checkout.

## Runtime shape

```text
M5Stack StopWatch V0.5 / Mooncake
├── official Apps
├── CC Island App
│   ├── BLE NUS
│   └── HTTP polling ─────────────┐
├── PrintSphere App               │
│   └── printsphere_m5 lifecycle  │
│       └── complete v1.6.2       │
│           ├── LAN/cloud MQTT ───┤
│           ├── REST/2FA/preview  ├── hub_wifi ── ESP-IDF Wi-Fi
│           ├── JPEG camera ──────┤
│           └── Web Config :8080 ─┘
└── M5Stack HAL
    ├── display/touch/LVGL
    ├── PMU/audio/vibration
    └── FAT/NVS
```

## Lifecycle contract

- `onCreate` starts PrintSphere's process-lifetime state/network task and
  creates its hidden private LVGL root under the official active screen.
- `onOpen` reveals the root, resumes App-scoped UI policy and leases the saved
  display/touch rotation through M5GFX + LVGL.
- `onRunning` handles Mooncake go-home input; PrintSphere workers remain
  independent and non-blocking.
- `onClose` hides the root, restores official rotation and brightness, and
  stops camera/preview work. Low-rate MQTT/state work may stay warm.

## Shared Wi-Fi and AP ownership

`hub_wifi` is process-lifetime infrastructure. It accepts a build-time CC
Island fallback plus persistent credentials loaded by PrintSphere, supports
STA/APSTA, scan and reconnect, and disables the PrintSphere setup AP after a
station address is acquired. M5Stack's Badge configuration page may temporarily
take exclusive AP control; explicit hooks stop reconnect races and restore the
previous shared mode afterward.

## OTA boundary

Both 6 MiB app partitions contain the entire official firmware plus both Apps.
PrintSphere's upload and URL OTA flows remain available, but each candidate is
checked for ESP app project name `StopWatch-UserDemo`. Standalone upstream
PrintSphere images are deliberately rejected because they would remove CC
Island and the official firmware shell.
