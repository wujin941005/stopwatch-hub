/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#include "app_codex.h"
#include "app_codex_config.h"
#include "ble/ble_nus.h"
#include "net/net.h"
#include "debug/debug_screenshot.h"
#include <hal/hal.h>
#include <mooncake.h>
#include <mooncake_log.h>
#include <assets/assets.h>
#include <smooth_lvgl.hpp>
#include <lvgl.h>
#include <cJSON.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

using namespace mooncake;
using namespace smooth_ui_toolkit::lvgl_cpp;

// Brand accent colors
static constexpr uint32_t kClaudeColor   = 0xF2854D;  // vivid orange
static constexpr uint32_t kCodexColor    = 0x3B9EFF;  // vivid blue
static constexpr uint32_t kOpencodeColor = 0x8B5CF6;  // violet
static constexpr uint32_t kDetailColor   = 0x8A8A8A;  // muted text
static constexpr uint32_t kCpuColor      = 0x22D3EE;  // cyan
static constexpr uint32_t kMemColor      = 0xA78BFA;  // violet
static constexpr uint32_t kDiskColor     = 0x4ADE80;  // green
static constexpr uint32_t kNetColor      = 0xFBBF24;  // amber

// 5h-window utilization that triggers a haptic alert when first crossed.
static constexpr int kAlertThreshold = 80;

// Horizontal swipe distance (px) required to switch pages manually.
static constexpr int kGestureMinDistance = 60;

namespace {

// --------------------------------------------------------------------------- //
// Small formatting helpers
// --------------------------------------------------------------------------- //
void fmt_tokens(char* buf, int sz, std::int64_t t)
{
    if (t >= 1000000000LL)
        std::snprintf(buf, sz, "%.1fB", t / 1e9);
    else if (t >= 1000000)
        std::snprintf(buf, sz, "%.1fM", t / 1e6);
    else if (t >= 1000)
        std::snprintf(buf, sz, "%.0fK", t / 1e3);
    else
        std::snprintf(buf, sz, "%lld", static_cast<long long>(t));
}

void fmt_reset(char* buf, int sz, int mins)
{
    if (mins <= 0) {
        std::snprintf(buf, sz, "reset ?");
        return;
    }
    int d = mins / 1440, h = (mins % 1440) / 60, m = mins % 60;
    if (d > 0)
        std::snprintf(buf, sz, "reset %dd%dh", d, h);
    else if (h > 0)
        std::snprintf(buf, sz, "reset %dh%02dm", h, m);
    else
        std::snprintf(buf, sz, "reset %dm", m);
}

int jint(cJSON* obj, const char* key)
{
    cJSON* it = cJSON_GetObjectItemCaseSensitive(obj, key);
    return it ? it->valueint : 0;
}

double jdbl(cJSON* obj, const char* key)
{
    cJSON* it = cJSON_GetObjectItemCaseSensitive(obj, key);
    return it ? it->valuedouble : 0.0;
}

std::int64_t jint64(cJSON* obj, const char* key)
{
    cJSON* it = cJSON_GetObjectItemCaseSensitive(obj, key);
    return it ? static_cast<std::int64_t>(it->valuedouble) : 0;
}

// --------------------------------------------------------------------------- //
// One usage-window row: label + bar + big % + reset line (pages layout).
// --------------------------------------------------------------------------- //
struct WinRow {
    lv_obj_t* container = nullptr;
    lv_obj_t* label = nullptr;
    lv_obj_t* bar   = nullptr;
    lv_obj_t* pct   = nullptr;
    lv_obj_t* reset = nullptr;

    void set_label(const char* t)
    {
        if (label) lv_label_set_text(label, t);
    }

    void set_visible(bool v)
    {
        if (container) {
            if (v)
                lv_obj_remove_flag(container, LV_OBJ_FLAG_HIDDEN);
            else
                lv_obj_add_flag(container, LV_OBJ_FLAG_HIDDEN);
        }
    }

    void apply(int v, int resetMin)
    {
        if (bar) lv_bar_set_value(bar, v, LV_ANIM_OFF);
        if (pct) {
            char b[8];
            std::snprintf(b, sizeof(b), "%d%%", v);
            lv_label_set_text(pct, b);
        }
        if (reset) {
            char b[20];
            fmt_reset(b, sizeof(b), resetMin);
            lv_label_set_text(reset, b);
        }
    }
};

// Label a window from its duration in seconds: 7d → "7D", 5h → "5H", ...
void derive_window_label(char* buf, int sz, int seconds)
{
    if (seconds >= 7 * 86400)
        std::snprintf(buf, sz, "7D");
    else if (seconds >= 2 * 86400)
        std::snprintf(buf, sz, "%dD", seconds / 86400);
    else if (seconds >= 86400)
        std::snprintf(buf, sz, "24H");
    else if (seconds >= 3600)
        std::snprintf(buf, sz, "%dH", seconds / 3600);
    else if (seconds >= 60)
        std::snprintf(buf, sz, "%dM", seconds / 60);
    else
        std::snprintf(buf, sz, "5H");
}

// --------------------------------------------------------------------------- //
// System row (bar + value)
// --------------------------------------------------------------------------- //
struct SysRow {
    lv_obj_t* bar = nullptr;
    lv_obj_t* val = nullptr;

    void apply(int pct)
    {
        if (bar) lv_bar_set_value(bar, pct, LV_ANIM_OFF);
        if (val) {
            char b[8];
            std::snprintf(b, sizeof(b), "%d%%", pct);
            lv_label_set_text(val, b);
        }
    }
};

// --------------------------------------------------------------------------- //
// Provider descriptor + compact row (classic "rows" layout).
// --------------------------------------------------------------------------- //
struct ProviderInfo {
    const char*           name;
    const char*           key;   // "c" / "x" / "o"
    const lv_image_dsc_t* logo;
    uint32_t              color;
};

const ProviderInfo kProviders[] = {
    {"Claude", "c", &logo_claude, kClaudeColor},
    {"Codex", "x", &logo_codex, kCodexColor},
    {"OpenCode", "o", &logo_opencode, kOpencodeColor},
};

const ProviderInfo* find_provider(const char* key)
{
    for (const auto& p : kProviders) {
        if (std::strcmp(p.key, key) == 0) return &p;
    }
    return nullptr;
}

struct UsageRow {
    lv_obj_t* big    = nullptr;
    lv_obj_t* bar    = nullptr;
    lv_obj_t* detail = nullptr;
    lv_obj_t* cost   = nullptr;

    void apply_codex(int h, int w, int r)
    {
        if (big) {
            char b[8];
            std::snprintf(b, sizeof(b), "%d%%", h);
            lv_label_set_text(big, b);
        }
        if (bar) lv_bar_set_value(bar, h, LV_ANIM_OFF);
        if (detail) {
            char b[40], rs[20];
            fmt_reset(rs, sizeof(rs), r);
            std::snprintf(b, sizeof(b), "7d %d%%  %s", w, rs);
            lv_label_set_text(detail, b);
        }
    }

    void apply_opencode(int h, int hr, int w)
    {
        if (big) {
            char b[8];
            std::snprintf(b, sizeof(b), "%d%%", h);
            lv_label_set_text(big, b);
        }
        if (bar) lv_bar_set_value(bar, h, LV_ANIM_OFF);
        if (detail) {
            char b[40], rs[20];
            fmt_reset(rs, sizeof(rs), hr);
            std::snprintf(b, sizeof(b), "wk %d%%  %s", w, rs);
            lv_label_set_text(detail, b);
        }
    }
};

// --------------------------------------------------------------------------- //
// Widget handles
// --------------------------------------------------------------------------- //
lv_obj_t* s_root = nullptr;

// Pages
lv_obj_t* s_page_ai       = nullptr;  // classic layout page 0
lv_obj_t* s_page_codex    = nullptr;  // pages layout page 0
lv_obj_t* s_page_opencode = nullptr;  // pages layout page 1
lv_obj_t* s_page_sys      = nullptr;
int s_page                = 0;
bool s_auto_switch        = true;
lv_obj_t* s_mode_lbl      = nullptr;

// Codex page (pages layout)
WinRow s_cx_5h;
WinRow s_cx_7d;
lv_obj_t* s_cx_cost = nullptr;
int s_cx_last_5h    = -1;
int s_cl_last_5h    = -1;

// OpenCode page (pages layout)
WinRow s_oc_5h;
WinRow s_oc_wk;
WinRow s_oc_mo;
lv_obj_t* s_oc_cost = nullptr;
int s_oc_last_5h    = -1;

// Classic layout rows
UsageRow s_top;
UsageRow s_bottom;
const ProviderInfo* s_top_prov = nullptr;
const ProviderInfo* s_bottom_prov = nullptr;

UsageRow* row_for_provider(const char* key)
{
    if (s_top_prov && std::strcmp(s_top_prov->key, key) == 0) return &s_top;
    if (s_bottom_prov && std::strcmp(s_bottom_prov->key, key) == 0) return &s_bottom;
    return nullptr;
}

// System page
SysRow s_cpu;
SysRow s_mem;
SysRow s_disk;
lv_obj_t* s_sys_title = nullptr;
lv_obj_t* s_net_lbl   = nullptr;

// Auto-switch + gesture state
uint32_t s_last_switch_ms = 0;
uint32_t s_auto_interval = 5000;
bool s_gesture_pressing = false;
lv_point_t s_gesture_start;
lv_point_t s_gesture_last;

int page_count()
{
    int n = kLayoutPages ? 2 : 1;  // provider pages
    return kShowSystemPage ? n + 1 : n;
}

lv_obj_t* page_obj(int idx)
{
    if (kLayoutPages) {
        if (idx == 0) return s_page_codex;
        if (idx == 1) return s_page_opencode;
        return s_page_sys;
    }
    return (idx == 0) ? s_page_ai : s_page_sys;
}

void show_page(int idx)
{
    s_page = ((idx % page_count()) + page_count()) % page_count();
    for (lv_obj_t* p : {s_page_codex, s_page_opencode, s_page_ai, s_page_sys}) {
        if (p) lv_obj_add_flag(p, LV_OBJ_FLAG_HIDDEN);
    }
    lv_obj_t* target = page_obj(s_page);
    if (target) lv_obj_remove_flag(target, LV_OBJ_FLAG_HIDDEN);
}

void update_mode_label()
{
    if (!s_mode_lbl) return;
    lv_label_set_text(s_mode_lbl, s_auto_switch ? "AUTO" : "MAN");
    lv_obj_set_style_text_color(s_mode_lbl,
                                lv_color_hex(s_auto_switch ? 0x22C55E : kDetailColor), 0);
}

// --------------------------------------------------------------------------- //
// Widget builders
// --------------------------------------------------------------------------- //
lv_obj_t* make_clean_container(lv_obj_t* parent)
{
    lv_obj_t* cont = lv_obj_create(parent);
    lv_obj_set_size(cont, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_opa(cont, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(cont, 0, 0);
    lv_obj_set_style_outline_width(cont, 0, 0);
    lv_obj_set_style_shadow_width(cont, 0, 0);
    lv_obj_set_style_radius(cont, 0, 0);
    lv_obj_set_style_pad_all(cont, 0, 0);
    lv_obj_remove_flag(cont, LV_OBJ_FLAG_SCROLLABLE);
    return cont;
}

void clean_style(lv_obj_t* o)
{
    lv_obj_set_style_bg_opa(o, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(o, 0, 0);
    lv_obj_set_style_outline_width(o, 0, 0);
    lv_obj_set_style_shadow_width(o, 0, 0);
    lv_obj_set_style_radius(o, 0, 0);
    lv_obj_set_style_pad_all(o, 0, 0);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE);
}

WinRow build_win_row(lv_obj_t* parent, int y, const char* label_text, uint32_t color)
{
    // Follows the original layout: a centered 300px container, children
    // aligned TOP_LEFT/TOP_RIGHT/TOP_MID inside it. Height 96 is enough that
    // the reset line is never clipped.
    WinRow r;

    lv_obj_t* cont = lv_obj_create(parent);
    lv_obj_set_size(cont, 300, 96);
    lv_obj_align(cont, LV_ALIGN_CENTER, 0, y);
    clean_style(cont);
    r.container = cont;

    r.label = lv_label_create(cont);
    lv_label_set_text(r.label, label_text);
    lv_obj_set_style_text_font(r.label, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(r.label, lv_color_hex(color), 0);
    lv_obj_align(r.label, LV_ALIGN_TOP_LEFT, 0, 2);

    r.pct = lv_label_create(cont);
    lv_obj_set_style_text_font(r.pct, &lv_font_maple_mono_medium_28, 0);
    lv_obj_set_style_text_color(r.pct, lv_color_hex(color), 0);
    lv_obj_align(r.pct, LV_ALIGN_TOP_RIGHT, 0, 2);

    r.bar = lv_bar_create(cont);
    lv_obj_set_size(r.bar, 300, 14);
    lv_obj_align(r.bar, LV_ALIGN_TOP_MID, 0, 34);
    lv_bar_set_range(r.bar, 0, 100);
    lv_obj_set_style_radius(r.bar, 7, LV_PART_MAIN);
    lv_obj_set_style_bg_color(r.bar, lv_color_hex(color), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(r.bar, LV_OPA_30, LV_PART_MAIN);
    lv_obj_set_style_shadow_width(r.bar, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(r.bar, 7, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(r.bar, lv_color_hex(color), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(r.bar, LV_OPA_COVER, LV_PART_INDICATOR);

    r.reset = lv_label_create(cont);
    lv_obj_set_style_text_font(r.reset, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(r.reset, lv_color_hex(kDetailColor), 0);
    lv_obj_align(r.reset, LV_ALIGN_TOP_MID, 0, 54);

    return r;
}

void build_provider_header(lv_obj_t* parent, int y, const lv_image_dsc_t* logo,
                           const char* name, uint32_t color)
{
    lv_obj_t* icon = lv_image_create(parent);
    lv_image_set_src(icon, logo);
    lv_obj_align(icon, LV_ALIGN_CENTER, 0, y);

    lv_obj_t* name_lbl = lv_label_create(parent);
    lv_label_set_text(name_lbl, name);
    lv_obj_set_style_text_font(name_lbl, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(name_lbl, lv_color_hex(color), 0);
    lv_obj_align(name_lbl, LV_ALIGN_CENTER, 0, y + 30);
}

lv_obj_t* build_cost_label(lv_obj_t* parent, int y, uint32_t color)
{
    lv_obj_t* lbl = lv_label_create(parent);
    lv_obj_set_style_text_font(lbl, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(lbl, lv_color_hex(color), 0);
    // Shift left a touch so the right-most digits don't get clipped by the
    // round screen edge.
    lv_obj_align(lbl, LV_ALIGN_CENTER, -28, y);
    return lbl;
}

UsageRow build_usage_row(lv_obj_t* parent, int y, const ProviderInfo& prov)
{
    UsageRow row;
    lv_obj_t* cont = lv_obj_create(parent);
    lv_obj_set_size(cont, 300, 140);
    lv_obj_align(cont, LV_ALIGN_CENTER, 0, y);
    clean_style(cont);

    lv_obj_t* icon = lv_image_create(cont);
    lv_image_set_src(icon, prov.logo);
    lv_obj_align(icon, LV_ALIGN_TOP_LEFT, 0, 2);

    lv_obj_t* name_lbl = lv_label_create(cont);
    lv_label_set_text(name_lbl, prov.name);
    lv_obj_set_style_text_font(name_lbl, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(name_lbl, lv_color_hex(prov.color), 0);
    lv_obj_align(name_lbl, LV_ALIGN_TOP_LEFT, 56, 8);

    row.big = lv_label_create(cont);
    lv_obj_set_style_text_font(row.big, &lv_font_maple_mono_medium_28, 0);
    lv_obj_set_style_text_color(row.big, lv_color_hex(prov.color), 0);
    lv_obj_align(row.big, LV_ALIGN_TOP_RIGHT, 0, 6);

    row.bar = lv_bar_create(cont);
    lv_obj_set_size(row.bar, 300, 24);
    lv_obj_align(row.bar, LV_ALIGN_TOP_MID, 0, 52);
    lv_bar_set_range(row.bar, 0, 100);
    lv_obj_set_style_radius(row.bar, 12, LV_PART_MAIN);
    lv_obj_set_style_bg_color(row.bar, lv_color_hex(prov.color), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(row.bar, LV_OPA_30, LV_PART_MAIN);
    lv_obj_set_style_shadow_width(row.bar, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(row.bar, 12, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(row.bar, lv_color_hex(prov.color), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(row.bar, LV_OPA_COVER, LV_PART_INDICATOR);

    row.detail = lv_label_create(cont);
    lv_obj_set_style_text_font(row.detail, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(row.detail, lv_color_hex(kDetailColor), 0);
    lv_obj_align(row.detail, LV_ALIGN_TOP_MID, 0, 84);

    row.cost = lv_label_create(cont);
    lv_obj_set_style_text_font(row.cost, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(row.cost, lv_color_hex(prov.color), 0);
    lv_obj_align(row.cost, LV_ALIGN_TOP_MID, 0, 112);

    return row;
}

SysRow build_sys_row(lv_obj_t* parent, int y_center, const char* name, uint32_t color)
{
    SysRow row;
    lv_obj_t* cont = lv_obj_create(parent);
    lv_obj_set_size(cont, 280, 70);
    lv_obj_align(cont, LV_ALIGN_CENTER, 0, y_center);
    clean_style(cont);

    lv_obj_t* name_lbl = lv_label_create(cont);
    lv_label_set_text(name_lbl, name);
    lv_obj_set_style_text_font(name_lbl, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(name_lbl, lv_color_hex(color), 0);
    lv_obj_align(name_lbl, LV_ALIGN_TOP_LEFT, 0, 6);

    row.val = lv_label_create(cont);
    lv_obj_set_style_text_font(row.val, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(row.val, lv_color_hex(color), 0);
    lv_obj_align(row.val, LV_ALIGN_TOP_RIGHT, 0, 6);

    row.bar = lv_bar_create(cont);
    lv_obj_set_size(row.bar, 280, 18);
    lv_obj_align(row.bar, LV_ALIGN_TOP_MID, 0, 48);
    lv_bar_set_range(row.bar, 0, 100);
    lv_obj_set_style_radius(row.bar, 9, LV_PART_MAIN);
    lv_obj_set_style_bg_color(row.bar, lv_color_hex(color), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(row.bar, LV_OPA_30, LV_PART_MAIN);
    lv_obj_set_style_shadow_width(row.bar, 0, LV_PART_MAIN);
    lv_obj_set_style_radius(row.bar, 9, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(row.bar, lv_color_hex(color), LV_PART_INDICATOR);
    lv_obj_set_style_bg_opa(row.bar, LV_OPA_COVER, LV_PART_INDICATOR);

    return row;
}

lv_obj_t* build_text_row(lv_obj_t* parent, int y_center, const char* name, uint32_t color)
{
    lv_obj_t* cont = lv_obj_create(parent);
    lv_obj_set_size(cont, 280, 70);
    lv_obj_align(cont, LV_ALIGN_CENTER, 0, y_center);
    clean_style(cont);

    lv_obj_t* name_lbl = lv_label_create(cont);
    lv_label_set_text(name_lbl, name);
    lv_obj_set_style_text_font(name_lbl, &MontserratSemiBold26, 0);
    lv_obj_set_style_text_color(name_lbl, lv_color_hex(color), 0);
    lv_obj_align(name_lbl, LV_ALIGN_TOP_LEFT, 0, 6);

    lv_obj_t* val = lv_label_create(cont);
    lv_obj_set_style_text_font(val, &lv_font_maple_mono_medium_24, 0);
    lv_obj_set_style_text_color(val, lv_color_hex(color), 0);
    lv_obj_align(val, LV_ALIGN_TOP_RIGHT, 0, 6);

    return val;
}

// --------------------------------------------------------------------------- //
// JSON → widgets
// --------------------------------------------------------------------------- //
void apply_row_cost(const char* key, double cost, std::int64_t tok)
{
    UsageRow* row = row_for_provider(key);
    if (!row || !row->cost) return;
    char tok_s[12], b[44];
    fmt_tokens(tok_s, sizeof(tok_s), tok);
    std::snprintf(b, sizeof(b), "today ~$%.2f %s", cost, tok_s);
    lv_label_set_text(row->cost, b);
}

void apply_cx_cost(double cost, std::int64_t tok)
{
    char tok_s[12], b[44];
    fmt_tokens(tok_s, sizeof(tok_s), tok);
    std::snprintf(b, sizeof(b), "today ~$%.2f %s", cost, tok_s);
    if (kLayoutPages) {
        if (s_cx_cost) lv_label_set_text(s_cx_cost, b);
    } else {
        apply_row_cost("x", cost, tok);
    }
}

void apply_oc_cost(double cost, std::int64_t tok)
{
    char tok_s[12], b[44];
    fmt_tokens(tok_s, sizeof(tok_s), tok);
    std::snprintf(b, sizeof(b), "today ~$%.2f %s", cost, tok_s);
    if (kLayoutPages) {
        if (s_oc_cost) lv_label_set_text(s_oc_cost, b);
    } else {
        apply_row_cost("o", cost, tok);
    }
}

bool update_claude_row(cJSON* root)
{
    if (kLayoutPages) return false;
    cJSON* obj = cJSON_GetObjectItem(root, "c");
    UsageRow* row = row_for_provider("c");
    if (!cJSON_IsObject(obj) || !row) return false;

    int h = jint(obj, "h");
    {
        LvglLockGuard lock;
        row->apply_codex(h, jint(obj, "w"), jint(obj, "hr"));
        apply_row_cost("c", jdbl(obj, "$"), jint64(obj, "t"));
    }

    bool crossed = (s_cl_last_5h >= 0 && s_cl_last_5h < kAlertThreshold &&
                    h >= kAlertThreshold);
    s_cl_last_5h = h;
    return crossed;
}

bool update_codex_page(cJSON* root)
{
    cJSON* obj = cJSON_GetObjectItem(root, "x");
    if (!cJSON_IsObject(obj)) return false;
    int h = jint(obj, "h"), hr = jint(obj, "hr"), hw = jint(obj, "hw");
    int w = jint(obj, "w"), wr = jint(obj, "wr"), ww = jint(obj, "ww");
    double cost = jdbl(obj, "$");
    std::int64_t tok = jint64(obj, "t");

    bool displayed = kLayoutPages;
    {
        LvglLockGuard lock;
        if (kLayoutPages) {
            char lab[8];
            derive_window_label(lab, sizeof(lab), hw);
            s_cx_5h.set_label(lab);
            s_cx_5h.apply(h, hr);
            if (w >= 0) {
                derive_window_label(lab, sizeof(lab), ww);
                s_cx_7d.set_label(lab);
                s_cx_7d.apply(w, wr);
                s_cx_7d.set_visible(true);
            } else {
                s_cx_7d.set_visible(false);
            }
            apply_cx_cost(cost, tok);
        } else {
            if (UsageRow* row = row_for_provider("x")) {
                row->apply_codex(h, w, hr);
                apply_cx_cost(cost, tok);
                displayed = true;
            }
        }
    }

    if (!displayed) return false;
    bool crossed = (s_cx_last_5h >= 0 && s_cx_last_5h < kAlertThreshold && h >= kAlertThreshold);
    s_cx_last_5h = h;
    return crossed;
}

bool update_opencode_page(cJSON* root)
{
    cJSON* obj = cJSON_GetObjectItem(root, "o");
    if (!cJSON_IsObject(obj)) return false;
    double today = jdbl(obj, "t");
    std::int64_t tokens = jint64(obj, "T");
    bool has_quota = cJSON_GetObjectItem(obj, "h") != nullptr;
    int h = has_quota ? jint(obj, "h") : 0;

    bool displayed = kLayoutPages;
    {
        LvglLockGuard lock;
        if (kLayoutPages) {
            if (has_quota) {
                s_oc_5h.apply(h, jint(obj, "hr"));
                s_oc_wk.apply(jint(obj, "w"), jint(obj, "wr"));
                s_oc_mo.apply(jint(obj, "m"), jint(obj, "mr"));
            } else {
                s_oc_5h.apply(0, 0);
                s_oc_wk.apply(0, 0);
                s_oc_mo.apply(0, 0);
            }
            apply_oc_cost(today, tokens);
        } else {
            if (UsageRow* row = row_for_provider("o")) {
                if (has_quota)
                    row->apply_opencode(h, jint(obj, "hr"), jint(obj, "w"));
                else
                    row->apply_opencode(0, 0, 0);
                apply_oc_cost(today, tokens);
                displayed = true;
            }
        }
    }

    if (!displayed) return false;
    bool crossed = (s_oc_last_5h >= 0 && s_oc_last_5h < kAlertThreshold && h >= kAlertThreshold);
    s_oc_last_5h = h;
    return crossed;
}

void update_sys(cJSON* obj)
{
    if (!cJSON_IsObject(obj)) return;
    cJSON* nm = cJSON_GetObjectItem(obj, "name");

    auto fmt_kbps = [](char* buf, int sz, double v) {
        if (v >= 1048576.0)
            std::snprintf(buf, sz, "%.2fG", v / 1048576.0);
        else if (v >= 1024.0)
            std::snprintf(buf, sz, "%.1fM", v / 1024.0);
        else
            std::snprintf(buf, sz, "%.0fK", v);
    };

    LvglLockGuard lock;
    if (s_sys_title && nm && nm->valuestring && nm->valuestring[0]) {
        lv_label_set_text(s_sys_title, nm->valuestring);
    }
    s_cpu.apply((int)jdbl(obj, "cpu"));
    s_mem.apply((int)jdbl(obj, "mem"));
    s_disk.apply((int)jdbl(obj, "disk"));
    if (s_disk.val) {
        char b[32], rd[12], wr[12];
        fmt_kbps(rd, sizeof(rd), jdbl(obj, "dr"));
        fmt_kbps(wr, sizeof(wr), jdbl(obj, "dw"));
        std::snprintf(b, sizeof(b), "R %s  W %s", rd, wr);
        lv_label_set_text(s_disk.val, b);
    }
    if (s_net_lbl) {
        char b[48], up[12], dn[12];
        fmt_kbps(up, sizeof(up), jdbl(obj, "nup"));
        fmt_kbps(dn, sizeof(dn), jdbl(obj, "ndn"));
        std::snprintf(b, sizeof(b), LV_SYMBOL_UP " %s  " LV_SYMBOL_DOWN " %s", up, dn);
        lv_label_set_text(s_net_lbl, b);
    }
}

void handle_line(const char* line)
{
    cJSON* root = cJSON_Parse(line);
    if (!root) return;

    bool alert = false;
    alert |= update_claude_row(root);
    alert |= update_codex_page(root);
    alert |= update_opencode_page(root);
    update_sys(cJSON_GetObjectItem(root, "sys"));

    cJSON_Delete(root);
    if (alert) GetHAL().vibrate(250, 100);
}

// --------------------------------------------------------------------------- //
// Swipe gesture (mirrors the factory watch-face manager)
// --------------------------------------------------------------------------- //
void update_gesture()
{
    lv_indev_t* indev = GetHAL().lvTouchpad;
    if (indev == nullptr) return;

    lv_point_t point;
    lv_indev_get_point(indev, &point);

    bool is_pressed = lv_indev_get_state(indev) == LV_INDEV_STATE_PRESSED;
    if (is_pressed) {
        if (!s_gesture_pressing) {
            s_gesture_pressing = true;
            s_gesture_start = point;
        }
        s_gesture_last = point;
        return;
    }

    if (!s_gesture_pressing) return;
    s_gesture_pressing = false;

    int delta_x = s_gesture_last.x - s_gesture_start.x;
    int delta_y = s_gesture_last.y - s_gesture_start.y;
    int abs_x = delta_x >= 0 ? delta_x : -delta_x;
    int abs_y = delta_y >= 0 ? delta_y : -delta_y;

    if (abs_x < kGestureMinDistance || abs_x <= abs_y) return;

    LvglLockGuard lock;
    show_page(s_page + (delta_x < 0 ? 1 : -1));
    s_last_switch_ms = GetHAL().millis();
    GetHAL().vibrate(40, 60);
}

}  // namespace

AppCodex::AppCodex()
{
    setAppInfo().name = "CC Island";
    setAppInfo().icon = (void*)&icon_cc_island;
}

void AppCodex::onCreate()
{
    mclog::tagInfo(getAppInfo().name, "on create");
}

void AppCodex::onOpen()
{
    mclog::tagInfo(getAppInfo().name, "on open");

    _key_manager = std::make_unique<input::KeyManager>();

    ble_nus::start("CC Island");
    net::start(net::kConfig);
    debug_shot::start();

    LvglLockGuard lock;

    s_root = lv_obj_create(lv_screen_active());
    lv_obj_set_size(s_root, LV_PCT(100), LV_PCT(100));
    lv_obj_set_style_bg_color(s_root, lv_color_black(), 0);
    lv_obj_set_style_border_width(s_root, 0, 0);
    lv_obj_set_style_shadow_width(s_root, 0, 0);
    lv_obj_set_style_radius(s_root, 0, 0);
    lv_obj_set_style_pad_all(s_root, 0, 0);
    lv_obj_remove_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    // Mode indicator (bottom center — top corners are off the round screen)
    s_mode_lbl = lv_label_create(s_root);
    lv_obj_set_style_text_font(s_mode_lbl, &lv_font_maple_mono_medium_24, 0);
    lv_obj_align(s_mode_lbl, LV_ALIGN_BOTTOM_MID, 0, -10);

    if (kLayoutPages) {
        // ---- Codex page ----
        s_page_codex = make_clean_container(s_root);
        build_provider_header(s_page_codex, -190, &logo_codex, "Codex", kCodexColor);
        s_cx_5h = build_win_row(s_page_codex, -105, "5H", kCodexColor);
        s_cx_7d = build_win_row(s_page_codex, -5, "7D", kCodexColor);
        s_cx_cost = build_cost_label(s_page_codex, 90, kCodexColor);

        // ---- OpenCode page ----
        s_page_opencode = make_clean_container(s_root);
        lv_obj_add_flag(s_page_opencode, LV_OBJ_FLAG_HIDDEN);
        build_provider_header(s_page_opencode, -190, &logo_opencode, "OpenCode", kOpencodeColor);
        s_oc_5h = build_win_row(s_page_opencode, -105, "5H", kOpencodeColor);
        s_oc_wk = build_win_row(s_page_opencode, -5, "WK", kOpencodeColor);
        s_oc_mo = build_win_row(s_page_opencode, 95, "MO", kOpencodeColor);
        s_oc_cost = build_cost_label(s_page_opencode, 155, kOpencodeColor);

        s_cx_5h.apply(0, 0);
        s_cx_7d.apply(0, 0);
        if (s_cx_cost) lv_label_set_text(s_cx_cost, "today ~$0.00 0");
        s_oc_5h.apply(0, 0);
        s_oc_wk.apply(0, 0);
        s_oc_mo.apply(0, 0);
        if (s_oc_cost) lv_label_set_text(s_oc_cost, "today ~$0.00 0");
    } else {
        // ---- Classic: one AI page with two providers ----
        s_page_ai = make_clean_container(s_root);
        const ProviderInfo* top = find_provider(kTopProvider);
        const ProviderInfo* bottom = find_provider(kBottomProvider);
        if (!top) top = &kProviders[1];
        if (!bottom) bottom = &kProviders[2];
        s_top_prov = top;
        s_bottom_prov = bottom;

        s_top = build_usage_row(s_page_ai, -80, *top);
        s_bottom = build_usage_row(s_page_ai, 80, *bottom);
        auto placeholder = [](UsageRow& row) {
            row.apply_codex(0, 0, 0);
            if (row.cost) lv_label_set_text(row.cost, "today ~$0.00 0");
        };
        placeholder(s_top);
        placeholder(s_bottom);
    }

    // ---- System page ----
    s_page_sys = make_clean_container(s_root);
    lv_obj_add_flag(s_page_sys, LV_OBJ_FLAG_HIDDEN);
    if (kShowSystemPage) {
        s_sys_title = lv_label_create(s_page_sys);
        lv_label_set_text(s_sys_title, "PC");
        lv_obj_set_style_text_font(s_sys_title, &MontserratSemiBold26, 0);
        lv_obj_set_style_text_color(s_sys_title, lv_color_hex(kDetailColor), 0);
        lv_obj_align(s_sys_title, LV_ALIGN_TOP_MID, 0, 18);

        s_cpu = build_sys_row(s_page_sys, -135, "CPU", kCpuColor);
        s_mem = build_sys_row(s_page_sys, -45, "MEM", kMemColor);
        s_disk = build_sys_row(s_page_sys, 45, "DSK", kDiskColor);
        s_net_lbl = build_text_row(s_page_sys, 135, "NET", kNetColor);
        // Maple Mono is ASCII-only. LVGL's built-in Montserrat font contains
        // the Font Awesome up/down symbols used by LV_SYMBOL_UP/DOWN.
        if (s_net_lbl) lv_obj_set_style_text_font(s_net_lbl, &lv_font_montserrat_24, 0);

        s_cpu.apply(0);
        s_mem.apply(0);
        s_disk.apply(0);
        if (s_disk.val) lv_label_set_text(s_disk.val, "R0K W0K");
        if (s_net_lbl) lv_label_set_text(s_net_lbl, LV_SYMBOL_UP " 0K  " LV_SYMBOL_DOWN " 0K");
    }

    s_auto_switch = (kAutoSwitchMs > 0);
    s_auto_interval = (kAutoSwitchMs > 0) ? kAutoSwitchMs : 5000;
    update_mode_label();

    show_page(0);
    s_gesture_pressing = false;
    s_last_switch_ms = GetHAL().millis();
}

void AppCodex::onRunning()
{
    if (_key_manager) {
        input::KeyEvent ev = _key_manager->update();
        if (ev == input::KeyEvent::GoHome) {
            close();
            return;
        }
        // Blue button (btnB / GoNext) -> ask the bridge for a fresh reading.
        if (ev == input::KeyEvent::GoNext) {
            ble_nus::request_refresh();
            net::request_refresh();
            GetHAL().vibrate(60, 80);
        }
        // Orange button (btnA / GoPrevious) -> toggle auto/manual switching.
        if (ev == input::KeyEvent::GoPrevious) {
            LvglLockGuard lock;
            s_auto_switch = !s_auto_switch;
            update_mode_label();
            s_last_switch_ms = GetHAL().millis();
            GetHAL().vibrate(60, 80);
        }
    }

    char line[512];
    if (ble_nus::poll_line(line, sizeof(line)) || net::poll_line(line, sizeof(line))) {
        handle_line(line);
    }

    if (int delta = debug_shot::take_page_delta(); delta != 0) {
        LvglLockGuard lock;
        show_page(s_page + delta);
        s_last_switch_ms = GetHAL().millis();
    }

    if (s_auto_switch && page_count() > 1) {
        uint32_t now = GetHAL().millis();
        if (now - s_last_switch_ms >= s_auto_interval) {
            s_last_switch_ms = now;
            LvglLockGuard lock;
            show_page(s_page + 1);
        }
    }

    update_gesture();
}

void AppCodex::onClose()
{
    mclog::tagInfo(getAppInfo().name, "on close");

    net::suspend();
    _key_manager.reset();

    LvglLockGuard lock;
    if (s_root) {
        lv_obj_delete(s_root);
        s_root = nullptr;
    }
    s_page_ai = nullptr;
    s_page_codex = nullptr;
    s_page_opencode = nullptr;
    s_page_sys = nullptr;
    s_mode_lbl = nullptr;
    s_cx_5h = WinRow{};
    s_cx_7d = WinRow{};
    s_cx_cost = nullptr;
    s_oc_5h = WinRow{};
    s_oc_wk = WinRow{};
    s_oc_mo = WinRow{};
    s_oc_cost = nullptr;
    s_top = UsageRow{};
    s_bottom = UsageRow{};
    s_top_prov = nullptr;
    s_bottom_prov = nullptr;
    s_sys_title = nullptr;
    s_cpu = SysRow{};
    s_mem = SysRow{};
    s_disk = SysRow{};
    s_net_lbl = nullptr;
    s_cx_last_5h = -1;
    s_cl_last_5h = -1;
    s_oc_last_5h = -1;
}
