/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

namespace hub_wifi {

// Build-time fallback until the shared persistent settings UI lands. The
// installer writes secrets only into the generated factory-firmware checkout.
struct BuildConfig {
    const char* ssid;
    const char* password;
};

inline constexpr BuildConfig kBuildConfig = {
    .ssid = "",
    .password = "",
};

}  // namespace hub_wifi
