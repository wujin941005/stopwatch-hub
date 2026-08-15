# Notices and upstream sources

StopWatch Hub is a private integration project for the M5Stack StopWatch C152.
It combines separately licensed work and does not claim ownership of upstream
projects or trademarks.

## CC Island

- Source: https://github.com/wujin941005/cc-island
- Direct upstream: https://github.com/alexjc-tech/cc-island
- Firmware foundation: https://github.com/m5stack/M5StopWatch-UserDemo
- License: MIT (`LICENSES/MIT.txt`)

The `bridge/`, `firmware/app_codex/`, related assets, and their integration
history originate from CC Island. Provider marks remain the property of their
respective owners and are used only to identify the corresponding services.

## PrintSphere

- Source: https://github.com/cptkirki/PrintSphere
- Imported version: v1.6.2
- Imported commit: `ed071d11dd09c2c93abdba62d8458e4b592f79d0`
- License: Federation Non-Commercial License v1.1
  (`LICENSES/FNCL-1.1.txt`)

PrintSphere-derived files are clearly marked with
`SPDX-License-Identifier: LicenseRef-FNCL-1.1`. StopWatch Hub modifies the
upstream application by separating hardware-independent printer state and
protocol logic from the board UI, lifecycle, Wi-Fi, storage, and OTA owners.
The port is named **Bambu Status** in the launcher; “PrintSphere” is used only
for factual source attribution. The generic launcher icon is an independent
design and is not a Bambu Lab or PrintSphere logo.

No affiliation with or endorsement by M5Stack, Bambu Lab, PrintSphere,
Anthropic, OpenAI, OpenCode, or any other referenced project is implied.
