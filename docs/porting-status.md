# PrintSphere to M5Stack StopWatch port status

Pinned source: PrintSphere v1.6.2 at
`ed071d11dd09c2c93abdba62d8458e4b592f79d0`.

| Area | Status | Notes |
| --- | --- | --- |
| Mixed-license and upstream metadata | Done | MIT + FNCL kept separate |
| Printer state model | Imported | `printsphere_core` |
| Bambu status/model parsing | Imported | Host smoke tests included |
| Mooncake app lifecycle | Skeleton | Opens, updates, closes cleanly |
| C152 platform adapter | Skeleton | No duplicate HAL initialization |
| Shared Wi-Fi owner | Next | CC Island currently owns its station task |
| LAN/cloud MQTT | Pending | Import after shared Wi-Fi is in place |
| Config/setup UI | Pending | Use hub storage; do not import standalone portal unchanged |
| Preview/camera | Pending | Must pause on app close; allocate from PSRAM |
| Audio/haptics | Pending | Route through M5Stack HAL |
| OTA | Pending | Combined image only; standalone PrintSphere OTA excluded |
| Error table | Pending | Move the large TSV out of the app image and into FAT |
| Real-device validation | Pending | Heap, Wi-Fi + NimBLE coexistence, battery, reconnects |

The checked-in partition table provides two 6 MiB OTA slots and a 3.8125 MiB
FAT partition on the C152's 16 MiB flash. The final combined image still needs
to be measured after MQTT, TLS, preview, and error lookup are integrated.

## Validation snapshot (2026-08-15)

- ESP-IDF v5.5.4 full build from a fresh factory-firmware checkout: passed.
- Generated image: 4,140,816 bytes (`0x3f2f10`).
- Existing CC Island image used as baseline: 4,051,712 bytes.
- Current vertical-slice increase: 89,104 bytes.
- Free space in each 6 MiB OTA slot: 2,150,640 bytes (`0x20d0f0`, 34%).
- Host C++17 smoke test for state/model/status parsing: passed with
  `-Wall -Wextra -Werror`.

This number covers the app skeleton, generic launcher icon, state model, and
status parser. It is not an estimate for the completed MQTT/TLS/cloud/camera
port; those pieces require a new measurement as they land.
