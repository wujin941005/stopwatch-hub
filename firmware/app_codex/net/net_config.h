/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <cstdint>

namespace net {

// WiFi + bridge settings for the CC Island app.
//
// Edit the values below for your network before flashing. The host is the
// machine running `bridge/codexisland_bridge.py --serve` — on WSL use the
// Windows host IP (or the mirrored-networking address), not the WSL IP.
struct Config {
    const char* ssid;
    const char* password;
    const char* host;    // HTTP server host (IP or hostname)
    uint16_t    port;    // bridge --serve port
    const char* path;    // watch payload endpoint
    uint32_t    poll_ms; // polling interval
};

// Defaults — replace with your own values.
inline const Config kConfig = {
    .ssid    = "YOUR_WIFI_SSID",
    .password = "YOUR_WIFI_PASSWORD",
    .host    = "192.168.1.100",
    .port    = 8080,
    .path    = "/stats",
    .poll_ms = 10000,
};

}  // namespace net
