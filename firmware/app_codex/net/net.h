/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include "net_config.h"

namespace net {

// Bring up WiFi once and start polling the bridge's HTTP endpoint. Idempotent
// — safe to call on every app open.
void start(const Config& cfg);

// Pause bridge polling while the app is closed. The shared hub Wi-Fi station
// stays available for other apps.
void suspend();

// If a complete '\n'-terminated line has arrived since the last call, copy it
// (without the newline) into `out` and return true. Otherwise return false.
bool poll_line(char* out, int out_size);

// Remember the latest complete, displayable payload. The cache is replayed on
// the next app open and periodically persisted so a bridge/Wi-Fi outage does
// not replace the last reading with an empty page after a watch restart.
void remember_line(const char* line);

// Ask the polling task to fetch a fresh reading now (blue button).
void request_refresh();

}  // namespace net
