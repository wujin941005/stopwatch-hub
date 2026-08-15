/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#include "printsphere_runtime.h"

#include <utility>

namespace printsphere_m5 {

PrintSphereRuntime& PrintSphereRuntime::instance()
{
    static PrintSphereRuntime runtime;
    return runtime;
}

void PrintSphereRuntime::initialize()
{
    if (initialized_) return;
    initialized_ = true;

    printsphere::PrinterSnapshot snapshot;
    snapshot.connection = printsphere::PrinterConnectionState::kWaitingForCredentials;
    snapshot.lifecycle = printsphere::PrintLifecycleState::kIdle;
    snapshot.stage = "setup";
    snapshot.detail = "Bambu setup required";
    snapshot.ui_status = "Setup required";
    state_.set_snapshot(std::move(snapshot));
}

void PrintSphereRuntime::resume()
{
    initialize();
    active_ = true;
}

void PrintSphereRuntime::suspend()
{
    // The core snapshot survives app switches. Future camera/preview workers
    // must pause here, while a low-rate status worker may remain connected.
    active_ = false;
}

void PrintSphereRuntime::update(uint32_t now_ms)
{
    if (!active_) return;
    last_update_ms_ = now_ms;
}

printsphere::PrinterSnapshot PrintSphereRuntime::snapshot() const
{
    return state_.snapshot();
}

}  // namespace printsphere_m5
