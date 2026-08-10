/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 *
 * Minimal NimBLE peripheral exposing the Nordic UART Service (NUS). The Mac
 * bridge connects as central and writes one JSON usage line at a time to the
 * RX characteristic; app_codex polls poll_line() to pick it up. We only need
 * the RX (write) path, but expose TX (notify) too so standard NUS centrals are
 * happy.
 */
#include "ble_nus.h"

#include <cstring>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <nvs_flash.h>
#include <mooncake_log.h>

#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

namespace {

constexpr const char* TAG = "ble_nus";

// Nordic UART Service UUIDs (128-bit, bytes little-endian for NimBLE macros).
// Service 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
const ble_uuid128_t kSvcUuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x01, 0x00, 0x40, 0x6e);
// RX 6E400002-... (central writes here)
const ble_uuid128_t kRxUuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x02, 0x00, 0x40, 0x6e);
// TX 6E400003-... (notify; unused for now)
const ble_uuid128_t kTxUuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x03, 0x00, 0x40, 0x6e);

constexpr int kLineMax = 512;

SemaphoreHandle_t g_mtx = nullptr;
char g_assembling[kLineMax];   // partial bytes received so far (host task only)
int g_assembling_len = 0;
char g_ready[kLineMax];        // last complete line, guarded by g_mtx
bool g_has_ready = false;

uint16_t g_tx_handle = 0;
uint16_t g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
uint8_t g_addr_type = 0;
const char* g_name = "CC Island";

void start_advertising();

// Push a finished line to the shared slot under the mutex.
void publish_line(const char* line, int len)
{
    if (len <= 0 || len >= kLineMax) return;
    if (xSemaphoreTake(g_mtx, portMAX_DELAY) == pdTRUE) {
        memcpy(g_ready, line, len);
        g_ready[len] = '\0';
        g_has_ready = true;
        xSemaphoreGive(g_mtx);
    }
}

// Append received bytes; emit a line whenever '\n' is seen.
void feed_bytes(const uint8_t* data, int len)
{
    for (int i = 0; i < len; i++) {
        char c = (char)data[i];
        if (c == '\n') {
            publish_line(g_assembling, g_assembling_len);
            g_assembling_len = 0;
        } else if (g_assembling_len < kLineMax - 1) {
            g_assembling[g_assembling_len++] = c;
        } else {
            g_assembling_len = 0;  // overflow guard: drop the runaway line
        }
    }
}

int rx_access_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt* ctxt, void*)
{
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint8_t buf[kLineMax];
        uint16_t n = OS_MBUF_PKTLEN(ctxt->om);
        if (n > sizeof(buf)) n = sizeof(buf);
        if (ble_hs_mbuf_to_flat(ctxt->om, buf, n, nullptr) == 0) {
            feed_bytes(buf, n);
        }
    }
    return 0;
}

int tx_access_cb(uint16_t, uint16_t, struct ble_gatt_access_ctxt*, void*)
{
    return 0;  // notify-only; nothing to read
}

const struct ble_gatt_chr_def kChrs[] = {
    {
        .uuid = &kRxUuid.u,
        .access_cb = rx_access_cb,
        .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP,
    },
    {
        .uuid = &kTxUuid.u,
        .access_cb = tx_access_cb,
        .flags = BLE_GATT_CHR_F_NOTIFY,
        .val_handle = &g_tx_handle,
    },
    {0},
};

const struct ble_gatt_svc_def kSvcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &kSvcUuid.u,
        .characteristics = kChrs,
    },
    {0},
};

int gap_event(struct ble_gap_event* event, void*)
{
    switch (event->type) {
        case BLE_GAP_EVENT_CONNECT:
            if (event->connect.status == 0)
                g_conn_handle = event->connect.conn_handle;
            else
                start_advertising();
            break;
        case BLE_GAP_EVENT_DISCONNECT:
            g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
            start_advertising();
            break;
        case BLE_GAP_EVENT_ADV_COMPLETE:
            start_advertising();
            break;
        default:
            break;
    }
    return 0;
}

void start_advertising()
{
    struct ble_gap_adv_params adv_params = {};
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;

    struct ble_hs_adv_fields fields = {};
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t*)g_name;
    fields.name_len = strlen(g_name);
    fields.name_is_complete = 1;
    int rc = ble_gap_adv_set_fields(&fields);
    if (rc != 0) {
        mclog::tagError(TAG, "ble_gap_adv_set_fields failed: {}", rc);
        return;
    }

    // Legacy advertising packets are limited to 31 bytes. Flags + complete
    // name + the 128-bit NUS UUID need 32 bytes, so advertise the name in the
    // primary packet and put the service UUID in the scan response.
    struct ble_hs_adv_fields response = {};
    response.uuids128 = &kSvcUuid;
    response.num_uuids128 = 1;
    response.uuids128_is_complete = 1;
    rc = ble_gap_adv_rsp_set_fields(&response);
    if (rc != 0) {
        mclog::tagError(TAG, "ble_gap_adv_rsp_set_fields failed: {}", rc);
        return;
    }

    rc = ble_gap_adv_start(g_addr_type, nullptr, BLE_HS_FOREVER, &adv_params,
                           gap_event, nullptr);
    if (rc != 0)
        mclog::tagError(TAG, "ble_gap_adv_start failed: {}", rc);
}

void on_sync()
{
    ble_hs_id_infer_auto(0, &g_addr_type);
    start_advertising();
    mclog::tagInfo(TAG, "advertising as '{}'", g_name);
}

void host_task(void*)
{
    nimble_port_run();  // returns only at nimble_port_stop()
    nimble_port_freertos_deinit();
}

}  // namespace

namespace ble_nus {

void start(const char* device_name)
{
    static bool started = false;
    if (started) return;
    started = true;

    if (device_name && device_name[0]) g_name = device_name;
    g_mtx = xSemaphoreCreateMutex();

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    if (nimble_port_init() != ESP_OK) {
        mclog::tagError(TAG, "nimble_port_init failed");
        return;
    }

    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_gatts_count_cfg(kSvcs);
    ble_gatts_add_svcs(kSvcs);
    ble_svc_gap_device_name_set(g_name);

    ble_hs_cfg.sync_cb = on_sync;

    nimble_port_freertos_init(host_task);
}

void request_refresh()
{
    if (g_conn_handle == BLE_HS_CONN_HANDLE_NONE) return;
    struct os_mbuf* om = ble_hs_mbuf_from_flat("R", 1);
    if (om) ble_gatts_notify_custom(g_conn_handle, g_tx_handle, om);
}

bool poll_line(char* out, int out_size)
{
    if (!g_mtx) return false;
    bool got = false;
    if (xSemaphoreTake(g_mtx, 0) == pdTRUE) {
        if (g_has_ready) {
            int n = (int)strlen(g_ready);
            if (n >= out_size) n = out_size - 1;
            memcpy(out, g_ready, n);
            out[n] = '\0';
            g_has_ready = false;
            got = true;
        }
        xSemaphoreGive(g_mtx);
    }
    return got;
}

}  // namespace ble_nus
