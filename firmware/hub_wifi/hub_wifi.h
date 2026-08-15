/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <cstddef>

namespace hub_wifi {

struct Config {
    const char* ssid = nullptr;
    const char* password = nullptr;
};

// Start or restore the process-wide Wi-Fi station. Calls are idempotent; all
// apps must use this service instead of initializing the ESP-IDF Wi-Fi driver.
void start(const Config& config);

bool connected();
bool copy_ip(char* output, std::size_t output_size);

// M5Stack's built-in configuration AP temporarily changes the global Wi-Fi
// mode. These hooks prevent reconnect races and restore STA mode afterwards.
void suspend_for_exclusive_use();
void resume_after_exclusive_use();

}  // namespace hub_wifi
