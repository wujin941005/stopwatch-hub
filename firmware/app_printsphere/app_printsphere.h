/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#pragma once

#include <apps/common/key_manager/key_manager.h>
#include <memory>
#include <mooncake.h>

class AppPrintSphere : public mooncake::AppAbility {
public:
    AppPrintSphere();

    void onCreate() override;
    void onOpen() override;
    void onRunning() override;
    void onClose() override;

private:
    std::unique_ptr<input::KeyManager> key_manager_;
};
