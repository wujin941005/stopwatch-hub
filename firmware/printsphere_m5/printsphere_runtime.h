/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#pragma once

#include <memory>

namespace printsphere {
class Application;
}

namespace printsphere_m5 {

// StopWatch-facing owner for the complete PrintSphere application. The
// upstream workers remain alive at low rate across app switches; the full LVGL
// dashboard and camera/preview work are gated by Mooncake open/close events.
class PrintSphereRuntime {
public:
    static PrintSphereRuntime& instance();

    void initialize();
    void resume();
    void suspend();
    void update();

    bool active() const { return active_; }

private:
    PrintSphereRuntime() = default;
    ~PrintSphereRuntime();

    std::unique_ptr<printsphere::Application> application_;
    bool initialized_ = false;
    bool active_ = false;
};

}  // namespace printsphere_m5
