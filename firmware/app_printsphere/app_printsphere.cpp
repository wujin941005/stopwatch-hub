/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#include "app_printsphere.h"

#include <assets/assets.h>
#include <mooncake_log.h>
#include <platform/printsphere_m5/printsphere_runtime.h>

AppPrintSphere::AppPrintSphere()
{
    setAppInfo().name = "PrintSphere";
    setAppInfo().icon = (void*)&icon_printsphere;
}

void AppPrintSphere::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
    printsphere_m5::PrintSphereRuntime::instance().initialize();
}

void AppPrintSphere::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");
    key_manager_ = std::make_unique<input::KeyManager>();
    printsphere_m5::PrintSphereRuntime::instance().resume();
}

void AppPrintSphere::onRunning()
{
    if (key_manager_ && key_manager_->update() == input::KeyEvent::GoHome) {
        close();
        return;
    }

    printsphere_m5::PrintSphereRuntime::instance().update();
}

void AppPrintSphere::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");
    printsphere_m5::PrintSphereRuntime::instance().suspend();
    key_manager_.reset();
}
