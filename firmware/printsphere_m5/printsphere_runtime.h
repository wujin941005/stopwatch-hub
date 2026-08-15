/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#pragma once

#include <cstdint>

#include "printsphere/printer_state.hpp"

namespace printsphere_m5 {

// StopWatch-facing lifecycle adapter for the hardware-independent core.
// Networking is deliberately absent until the hub has one shared Wi-Fi owner.
class PrintSphereRuntime {
public:
    static PrintSphereRuntime& instance();

    void initialize();
    void resume();
    void suspend();
    void update(uint32_t now_ms);

    bool active() const { return active_; }
    printsphere::PrinterSnapshot snapshot() const;

private:
    PrintSphereRuntime() = default;

    printsphere::PrinterStateStore state_;
    bool initialized_ = false;
    bool active_ = false;
    uint32_t last_update_ms_ = 0;
};

}  // namespace printsphere_m5
