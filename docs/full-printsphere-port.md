# Full PrintSphere app port contract

The target is feature equivalence with PrintSphere v1.6.2, not a reduced
printer-status widget. PrintSphere becomes one Mooncake app inside the pinned
M5Stack StopWatch V0.5 firmware and coexists with CC Island in the same image.

## Feature matrix

| PrintSphere v1.6.2 capability | StopWatch Hub target | Integration owner |
| --- | --- | --- |
| Local Bambu MQTT and V1/V2 parsing | Preserve | PrintSphere clients over `hub_wifi` |
| Bambu Cloud login, verification/2FA, MQTT and REST | Preserve | PrintSphere cloud client |
| Hybrid/cloud/local source resolver | Preserve | PrintSphere status resolver |
| Progress, layers, temperatures, stages and error details | Preserve | PrintSphere core + UI |
| AMS units, trays and external spool pages | Preserve | PrintSphere UI |
| Cloud cover preview and project metadata | Preserve | PrintSphere cloud client + UI |
| Local JPEG camera for supported printers | Preserve | PrintSphere camera client + UI |
| RTSP-family limitation | Same as upstream | ESP32-S3 cannot decode these streams |
| Chamber-light and optional print controls | Preserve upstream behavior | PrintSphere clients + UI |
| Multi-printer profiles and live switching | Preserve | Shared NVS namespace |
| Web Config, temporary PIN and live reconnect | Preserve | PrintSphere HTTP portal |
| Wi-Fi scan, station setup and fallback AP | Preserve behavior | `hub_wifi`, one process owner |
| Rotation, colors, time zone and power policy | Preserve | PrintSphere settings + M5 HAL |
| Sound events and custom WAV uploads | Preserve | M5 audio HAL + shared FAT storage |
| Battery and charging status | Preserve | M5 HAL; no second PMU initialization |
| USB provisioning | Preserve where it does not steal an active console | Hub service adapter |
| OTA upload and URL update | Preserve as combined-firmware OTA | StopWatch Hub OTA slots |

## Non-negotiable ownership rules

- PrintSphere must not initialize the display, touch controller, LVGL task,
  PMU, audio codec, I2C bus, NVS, default event loop, or Wi-Fi driver again.
- Its 466 x 466 LVGL dashboard is retained beneath a private App root. The root
  is hidden outside the App; camera, preview, brightness and rotation work are
  suspended/restored on close without rebuilding thousands of LVGL objects.
- Network clients may keep low-rate state while the app is closed; camera,
  preview decoding, animations, and screen-owned objects must pause or release.
- PrintSphere settings use their own NVS namespace. Uploaded sounds and other
  files use the official firmware's `/spiflash` FAT volume.
- OTA endpoints accept only a StopWatch Hub combined image. An upstream
  standalone PrintSphere image is not compatible with this firmware.

## Verified compatibility facts

- Both projects use ESP-IDF 5.5.4 and LVGL 9.5.0.
- Both target a 466 x 466 ESP32-S3 AMOLED display.
- The official M5Stack HAL already owns brightness, battery/charging, audio,
  vibration, filesystem, display, touch, and LVGL locking APIs needed by the
  port.

## Current verification boundary

The full source, adapters and combined image compile under ESP-IDF v5.5.4 and
fit both 6 MiB OTA slots. Host tests verify source inventory, adapter ownership,
lifecycle/OTA guards and deterministic materialization. Physical C152 testing
is still required before claiming runtime validation of Wi-Fi/BLE coexistence,
live Bambu Cloud/2FA, camera heap behavior, audio, all rotations and OTA.
