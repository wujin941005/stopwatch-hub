/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

namespace ble_nus {

// Bring up the NimBLE host once and start advertising the Nordic UART Service
// under the given device name. Idempotent — safe to call on every app open.
void start(const char* device_name);

// If a complete '\n'-terminated line has arrived since the last call, copy it
// (without the newline) into `out` and return true. Otherwise return false.
bool poll_line(char* out, int out_size);

// Notify the connected central (the Mac bridge) to push a fresh reading now.
// No-op if nothing is connected.
void request_refresh();

}  // namespace ble_nus
