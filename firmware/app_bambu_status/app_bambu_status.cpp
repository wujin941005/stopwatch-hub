/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 */
#include "app_bambu_status.h"

#include <assets/assets.h>
#include <hal/hal.h>
#include <mooncake_log.h>
#include <platform/printsphere_m5/printsphere_runtime.h>

namespace {

constexpr uint32_t kAccentColor = 0x20C997;
constexpr uint32_t kMutedColor = 0x8A969F;
constexpr uint32_t kRefreshMs = 500;

void clean_panel(lv_obj_t* object)
{
    lv_obj_set_style_bg_color(object, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(object, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(object, 0, 0);
    lv_obj_set_style_outline_width(object, 0, 0);
    lv_obj_set_style_shadow_width(object, 0, 0);
    lv_obj_set_style_radius(object, 0, 0);
    lv_obj_set_style_pad_all(object, 0, 0);
    lv_obj_remove_flag(object, LV_OBJ_FLAG_SCROLLABLE);
}

}  // namespace

AppBambuStatus::AppBambuStatus()
{
    setAppInfo().name = "Bambu Status";
    setAppInfo().icon = (void*)&icon_bambu_status;
}

void AppBambuStatus::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
    printsphere_m5::PrintSphereRuntime::instance().initialize();
}

void AppBambuStatus::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");
    key_manager_ = std::make_unique<input::KeyManager>();
    printsphere_m5::PrintSphereRuntime::instance().resume();

    LvglLockGuard lock;
    root_ = lv_obj_create(lv_screen_active());
    lv_obj_set_size(root_, LV_PCT(100), LV_PCT(100));
    clean_panel(root_);

    lv_obj_t* title = lv_label_create(root_);
    lv_label_set_text(title, "Bambu Status");
    lv_obj_set_style_text_font(title, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(title, lv_color_hex(kAccentColor), 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 70);

    status_label_ = lv_label_create(root_);
    lv_obj_set_style_text_font(status_label_, &lv_font_maple_mono_medium_28, 0);
    lv_obj_set_style_text_color(status_label_, lv_color_white(), 0);
    lv_obj_align(status_label_, LV_ALIGN_CENTER, 0, -18);

    detail_label_ = lv_label_create(root_);
    lv_obj_set_width(detail_label_, 330);
    lv_label_set_long_mode(detail_label_, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_align(detail_label_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_font(detail_label_, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(detail_label_, lv_color_hex(kMutedColor), 0);
    lv_obj_align(detail_label_, LV_ALIGN_CENTER, 0, 42);

    lv_obj_t* attribution = lv_label_create(root_);
    lv_label_set_text(attribution, "Core: PrintSphere v1.6.2");
    lv_obj_set_style_text_font(attribution, &lv_font_montserrat_14, 0);
    lv_obj_set_style_text_color(attribution, lv_color_hex(0x5E6972), 0);
    lv_obj_align(attribution, LV_ALIGN_BOTTOM_MID, 0, -62);

    refreshView();
    last_refresh_ms_ = GetHAL().millis();
}

void AppBambuStatus::onRunning()
{
    if (key_manager_ && key_manager_->update() == input::KeyEvent::GoHome) {
        close();
        return;
    }

    const uint32_t now = GetHAL().millis();
    printsphere_m5::PrintSphereRuntime::instance().update(now);
    if (now - last_refresh_ms_ >= kRefreshMs) {
        LvglLockGuard lock;
        refreshView();
        last_refresh_ms_ = now;
    }
}

void AppBambuStatus::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");
    printsphere_m5::PrintSphereRuntime::instance().suspend();
    key_manager_.reset();

    LvglLockGuard lock;
    if (root_) lv_obj_delete(root_);
    root_ = nullptr;
    status_label_ = nullptr;
    detail_label_ = nullptr;
    last_refresh_ms_ = 0;
}

void AppBambuStatus::refreshView()
{
    const printsphere::PrinterSnapshot snapshot =
        printsphere_m5::PrintSphereRuntime::instance().snapshot();
    if (status_label_) {
        const char* status = snapshot.ui_status.empty()
                                 ? printsphere::to_string(snapshot.lifecycle)
                                 : snapshot.ui_status.c_str();
        lv_label_set_text(status_label_, status);
    }
    if (detail_label_) lv_label_set_text(detail_label_, snapshot.detail.c_str());
}
