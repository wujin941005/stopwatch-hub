# StopWatch Hub architecture

StopWatch Hub is one ESP-IDF firmware image with multiple Mooncake apps. It is
not a boot selector and it does not embed two standalone firmware images.

## Ownership

| Resource | Sole owner | Consumers |
| --- | --- | --- |
| Display, touch, LVGL | M5Stack factory HAL | Launcher, CC Island, Bambu Status |
| PMU, battery, vibration, audio, I2C | M5Stack factory HAL | All apps through HAL APIs |
| Mooncake loop | `main.cpp` from factory firmware | All installed apps |
| Wi-Fi station and credentials | `hub_wifi` | CC Island polling, Bambu MQTT/cloud |
| Persistent configuration | shared hub storage (planned) | App-specific namespaces |
| OTA slots and update policy | hub firmware (planned) | Whole combined image only |

An app must not call board initialization, create a second default event loop,
or run its own infinite top-level loop.

`hub_wifi` is process-lifetime infrastructure. M5Stack's badge configuration
portal may temporarily switch the global driver to AP mode through explicit
exclusive-use hooks; station mode is restored when that session ends. App-level
polling can pause independently without tearing down the shared station.

## Port boundaries

```text
Bambu Status (Mooncake App)
    UI construction, input, onOpen/onRunning/onClose
                    |
                    v
printsphere_m5
    C152 lifecycle adapter and future shared-service bindings
                    |
                    v
printsphere_core
    printer state, status parsing, MQTT/cloud protocol logic
```

`printsphere_core` keeps upstream PrintSphere names where that reduces porting
diffs. `printsphere_m5` is the only layer allowed to translate between the core
and StopWatch/Mooncake facilities.

## Lifecycle contract

- `onCreate`: initialize cheap process-lifetime state only.
- `onOpen`: create the app UI and resume status work.
- `onRunning`: update the core and copy snapshots into LVGL under the HAL lock.
- `onClose`: pause expensive preview/camera work, release the app UI, and leave
  no app-owned LVGL objects behind.

The initial vertical slice intentionally has no Bambu networking. This proves
the app/core/platform boundary without risking a second `esp_wifi_init()`.
