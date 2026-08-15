/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#include "printsphere_runtime.h"

#include <esp_log.h>
#include <printsphere/application.hpp>

namespace printsphere_m5 {

namespace {
constexpr char kTag[] = "printsphere.m5";
}

PrintSphereRuntime& PrintSphereRuntime::instance()
{
    static PrintSphereRuntime runtime;
    return runtime;
}

PrintSphereRuntime::~PrintSphereRuntime() = default;

void PrintSphereRuntime::initialize()
{
    if (initialized_) return;
    application_ = std::make_unique<printsphere::Application>();
    const esp_err_t result = application_->start();
    if (result != ESP_OK) {
        ESP_LOGE(kTag, "Failed to start PrintSphere: %s", esp_err_to_name(result));
        application_.reset();
        return;
    }
    initialized_ = true;
}

void PrintSphereRuntime::resume()
{
    initialize();
    if (!application_) return;
    active_ = true;
    application_->resume();
}

void PrintSphereRuntime::suspend()
{
    active_ = false;
    if (application_) application_->suspend();
}

void PrintSphereRuntime::update()
{
    // PrintSphere owns its network/state worker task. Mooncake's running hook
    // only handles app-level input and intentionally stays non-blocking.
}

}  // namespace printsphere_m5
