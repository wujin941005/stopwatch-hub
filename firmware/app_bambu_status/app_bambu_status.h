/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#pragma once

#include <apps/common/key_manager/key_manager.h>
#include <lvgl.h>
#include <memory>
#include <mooncake.h>

class AppBambuStatus : public mooncake::AppAbility {
public:
    AppBambuStatus();

    void onCreate() override;
    void onOpen() override;
    void onRunning() override;
    void onClose() override;

private:
    void refreshView();

    std::unique_ptr<input::KeyManager> key_manager_;
    lv_obj_t* root_ = nullptr;
    lv_obj_t* status_label_ = nullptr;
    lv_obj_t* detail_label_ = nullptr;
    uint32_t last_refresh_ms_ = 0;
};
