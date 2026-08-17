/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

#include <esp_err.h>

namespace hub_wifi {

struct AccessPoint {
    std::string ssid;
    int rssi = -127;
    bool auth_required = true;
};

// Initialize the process-wide ESP-IDF network stack and Wi-Fi driver without
// selecting a mode. Safe to call repeatedly and before credentials exist.
esp_err_t initialize();

// Start or restore the process-wide Wi-Fi station. Calls are idempotent; all
// apps must use this service instead of initializing the ESP-IDF Wi-Fi driver.
void start();

// Replace the active station credentials. PrintSphere persists these in its
// own NVS namespace; the build-time values remain a first-boot fallback for CC
// Island installations that predate the shared setup UI.
esp_err_t configure_station(const char* ssid, const char* password);

// PrintSphere's fallback AP shares the already initialized driver. It can stay
// active alongside the station while provisioning and is disabled after the
// station receives an address.
esp_err_t start_setup_access_point(const char* ssid, const char* password);
esp_err_t stop_setup_access_point();
bool setup_access_point_active();
bool copy_setup_access_point_ssid(char* output, std::size_t output_size);
const char* setup_access_point_ip();

std::vector<AccessPoint> scan_visible_access_points();

bool configured();
bool connected();
// Copy the SSID currently selected by the shared station service. This exposes
// only the network name so setup UIs can reflect the device-wide Wi-Fi without
// ever reading or rendering the password.
bool copy_station_ssid(char* output, std::size_t output_size);
bool copy_ip(char* output, std::size_t output_size);

// M5Stack's built-in configuration AP temporarily changes the global Wi-Fi
// mode. These hooks prevent reconnect races and restore STA mode afterwards.
void suspend_for_exclusive_use();
void resume_after_exclusive_use();

}  // namespace hub_wifi
