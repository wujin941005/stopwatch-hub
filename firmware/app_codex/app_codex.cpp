/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#include "app_codex.h"
#include "ble/ble_nus.h"
#include <hal/hal.h>
#include <mooncake.h>
#include <mooncake_log.h>
#include <assets/assets.h>
#include <smooth_lvgl.hpp>
#include <lvgl.h>
#include <cJSON.h>
#include <cstdio>
#include <cstring>

using namespace mooncake;
using namespace smooth_ui_toolkit::lvgl_cpp;

// Brand accent colors
static constexpr uint32_t kClaudeColor = 0xF2854D;  // vivid orange (Anthropic-ish)
static constexpr uint32_t kCodexColor  = 0x3B9EFF;  // vivid blue
static constexpr uint32_t kDetailColor = 0x8A8A8A;  // muted text

// 5h-window utilization that triggers a haptic alert when first crossed.
static constexpr int kAlertThreshold = 80;

namespace {

void fmt_tokens(char* buf, int sz, long t)
{
    if (t >= 1000000)
        std::snprintf(buf, sz, "%.1fM", t / 1e6);
    else if (t >= 1000)
        std::snprintf(buf, sz, "%.0fK", t / 1e3);
    else
        std::snprintf(buf, sz, "%ld", t);
}

// Per-provider widget handles + last value, so BLE updates can refresh in place.
struct ProviderRow {
    lv_obj_t* bar    = nullptr;
    lv_obj_t* pct5h  = nullptr;
    lv_obj_t* detail = nullptr;  // "7d N%  reset HhMMm"
    lv_obj_t* cost   = nullptr;  // "$X.XX  N.NM"
    int last_p5h     = -1;       // for threshold-crossing haptics

    void apply(int p5h, int p7d, int reset5hMin, double costUsd, long tokens)
    {
        if (bar) lv_bar_set_value(bar, p5h, LV_ANIM_OFF);
        if (pct5h) {
            char b[8];
            std::snprintf(b, sizeof(b), "%d%%", p5h);
            lv_label_set_text(pct5h, b);
        }
        if (detail) {
            char b[40];
            std::snprintf(b, sizeof(b), "7d %d%%  reset %dh%02dm", p7d, reset5hMin / 60, reset5hMin % 60);
            lv_label_set_text(detail, b);
        }
        if (cost) {
            char tok[12];
            fmt_tokens(tok, sizeof(tok), tokens);
            char b[32];
            std::snprintf(b, sizeof(b), "$%.2f  %s", costUsd, tok);
            lv_label_set_text(cost, b);
        }
    }
};

lv_obj_t* s_root = nullptr;
ProviderRow s_claude;
ProviderRow s_codex;

// Build one provider row inside `parent`, vertically centered at y_center.
ProviderRow build_row(lv_obj_t* parent, int y_center, const lv_image_dsc_t* logo, const char* name, uint32_t color)
{
    ProviderRow row;

    lv_obj_t* cont = lv_obj_create(parent);
    lv_obj_set_size(cont, 300, 140);
    lv_obj_align(cont, LV_ALIGN_CENTER, 0, y_center);
    lv_obj_set_style_bg_opa(cont, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(cont, 0, 0);
    lv_obj_set_style_outline_width(cont, 0, 0);
    lv_obj_set_style_shadow_width(cont, 0, 0);
    lv_obj_set_style_radius(cont, 0, 0);
    lv_obj_set_style_pad_all(cont, 0, 0);
    lv_obj_remove_flag(cont, LV_OBJ_FLAG_SCROLLABLE);

    // Official brand logo (48x48 RGB565 bitmap)
    lv_obj_t* icon = lv_image_create(cont);
    lv_image_set_src(icon, logo);
    lv_obj_align(icon, LV_ALIGN_TOP_LEFT, 0, 2);

    // Provider name (brand-colored to clearly distinguish the two rows)
    lv_obj_t* name_lbl = lv_label_create(cont);
    lv_label_set_text(name_lbl, name);
    lv_obj_set_style_text_font(name_lbl, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(name_lbl, lv_color_hex(color), 0);
    lv_obj_align(name_lbl, LV_ALIGN_TOP_LEFT, 56, 8);

    // Big 5h percentage (right aligned)
    row.pct5h = lv_label_create(cont);
    lv_obj_set_style_text_font(row.pct5h, &lv_font_maple_mono_medium_28, 0);
    lv_obj_set_style_text_color(row.pct5h, lv_color_hex(color), 0);
    lv_obj_align(row.pct5h, LV_ALIGN_TOP_RIGHT, 0, 6);

    // 5h utilization bar — dim brand-tinted track + solid brand indicator
    row.bar = lv_bar_create(cont);
    lv_obj_set_size(row.bar, 300, 24);
    lv_obj_align(row.bar, LV_ALIGN_TOP_MID, 0, 52);
    lv_bar_set_range(row.bar, 0, 100);
    lv_obj_set_style_radius(row.bar, 12, LV_PART_MAIN);
    lv_obj_set_style_bg_color(row.bar, lv_color_hex(color), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(row.bar, LV_OPA_30, LV_PART_MAIN);
    lv_obj_set_style_shadow_width(row.bar, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(row.bar, 12, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(row.bar, lv_color_hex(color), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(row.bar, LV_OPA_COVER, LV_PART_INDICATOR);

    // 7d + reset line
    row.detail = lv_label_create(cont);
    lv_obj_set_style_text_font(row.detail, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(row.detail, lv_color_hex(kDetailColor), 0);
    lv_obj_align(row.detail, LV_ALIGN_TOP_MID, 0, 84);

    // today cost + tokens line
    row.cost = lv_label_create(cont);
    lv_obj_set_style_text_font(row.cost, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(row.cost, lv_color_hex(color), 0);
    lv_obj_align(row.cost, LV_ALIGN_TOP_MID, 0, 112);

    return row;
}

// Pull one provider's fields out of a parsed JSON object and refresh its row.
// Returns true if the 5h window just crossed the alert threshold upward.
bool update_from_json(ProviderRow& row, cJSON* obj)
{
    if (!cJSON_IsObject(obj)) return false;
    int h = cJSON_GetObjectItem(obj, "h") ? cJSON_GetObjectItem(obj, "h")->valueint : 0;
    int d = cJSON_GetObjectItem(obj, "d") ? cJSON_GetObjectItem(obj, "d")->valueint : 0;
    int r = cJSON_GetObjectItem(obj, "r") ? cJSON_GetObjectItem(obj, "r")->valueint : 0;
    cJSON* cj = cJSON_GetObjectItem(obj, "$");
    cJSON* tj = cJSON_GetObjectItem(obj, "t");
    double cost = cj ? cj->valuedouble : 0.0;
    long tok = tj ? (long)tj->valuedouble : 0;

    {
        LvglLockGuard lock;
        row.apply(h, d, r, cost, tok);
    }

    bool crossed = (row.last_p5h >= 0 && row.last_p5h < kAlertThreshold && h >= kAlertThreshold);
    row.last_p5h = h;
    return crossed;
}

}  // namespace

AppCodex::AppCodex()
{
    setAppInfo().name = "CC Island";
    setAppInfo().icon = (void*)&icon_codex;
}

void AppCodex::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
}

void AppCodex::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");

    _key_manager = std::make_unique<input::KeyManager>();

    // Bring up BLE NUS (idempotent — only the first open actually starts it).
    ble_nus::start("CC Island");

    LvglLockGuard lock;

    // Full-screen black root
    s_root = lv_obj_create(lv_screen_active());
    lv_obj_set_size(s_root, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_color(s_root, lv_color_black(), 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_shadow_width(s_root, 0, 0);
    lv_obj_set_style_radius(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 0, 0);
    lv_obj_remove_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    s_claude = build_row(s_root, -80, &logo_claude, "Claude", kClaudeColor);
    s_codex  = build_row(s_root, 80, &logo_codex, "Codex", kCodexColor);

    // Placeholder values until the first BLE push arrives.
    s_claude.apply(0, 0, 0, 0.0, 0);
    s_codex.apply(0, 0, 0, 0.0, 0);
}

void AppCodex::onRunning()
{
    if (_key_manager) {
        input::KeyEvent ev = _key_manager->update();
        if (ev == input::KeyEvent::GoHome) {
            close();
            return;
        }
        // Blue button (G1) -> ask the Mac to push a fresh reading now.
        if (ev == input::KeyEvent::GoNext) {
            ble_nus::request_refresh();
            GetHAL().vibrate(60, 80);  // tactile "got it"
        }
    }

    // Apply the latest usage line pushed over BLE, if any.
    char line[256];
    if (ble_nus::poll_line(line, sizeof(line))) {
        cJSON* root = cJSON_Parse(line);
        if (root) {
            bool a = update_from_json(s_claude, cJSON_GetObjectItem(root, "c"));
            bool b = update_from_json(s_codex, cJSON_GetObjectItem(root, "x"));
            cJSON_Delete(root);
            if (a || b) GetHAL().vibrate(250, 100);
        }
    }
}

void AppCodex::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");

    _key_manager.reset();

    LvglLockGuard lock;
    if (s_root) {
        lv_obj_delete(s_root);
        s_root = nullptr;
    }
    s_claude = ProviderRow{};
    s_codex  = ProviderRow{};
}
