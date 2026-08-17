/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

#include <cstdint>

#include <esp_err.h>

namespace hub_time {

// Start the process-wide SNTP client. Safe to call repeatedly; hub_wifi calls
// this automatically after the station receives an IP address.
esp_err_t start_sntp();

// Called by the shared Wi-Fi service task while connected. Initializes SNTP if
// needed and persists completed synchronization to RTC outside tcpip_thread.
esp_err_t maintain_sntp();

// True after an SNTP callback, or when the RX8130-restored system clock is
// plausible for this firmware build. Cloud TLS must not start before this is
// true because an invalid future RTC value breaks certificate validation.
bool time_is_trustworthy();

// Whether this boot has completed an SNTP synchronization.
bool sntp_synchronized();
bool sntp_started();
int sntp_last_error();
uint8_t sntp_reachability(unsigned int server_index);

}  // namespace hub_time
