/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 *
 * Minimal Wi-Fi station + polling HTTP client for the CC Island app.
 *
 * The watch connects to the local AP and polls the bridge's `/stats` endpoint
 * on a timer. Each successful response is stored as one line and handed to
 * app_codex via poll_line(), mirroring the interface the old BLE NUS used so
 * the app code barely changes. HTTP is done over a raw lwIP socket so the
 * app needs no extra ESP-IDF components beyond the standard Wi-Fi stack.
 */
#include "net.h"

#include <atomic>
#include <cstring>
#include <cstdio>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include <esp_heap_caps.h>
#include <nvs.h>
#include <lwip/sockets.h>
#include <lwip/netdb.h>
#include <mooncake_log.h>
#include <services/hub_wifi/hub_wifi.h>

using namespace net;

namespace {

constexpr const char* TAG = "net";

constexpr int kLineMax = 512;
constexpr int kHttpGetBuf = kLineMax;
constexpr int kConnectTimeoutMs = 5000;
constexpr uint32_t kCachePersistMinIntervalMs = 5 * 60 * 1000;
constexpr const char* kCacheNamespace = "cc_island";
constexpr const char* kCacheKey = "stats";

Config g_cfg = {};
std::atomic<bool> g_cfg_set{false};
std::atomic<bool> g_active{false};

SemaphoreHandle_t g_mtx = nullptr;
char g_ready[kLineMax];     // last complete line, guarded by g_mtx
bool g_has_ready = false;
std::atomic<bool> g_wake{false};  // blue button -> poll immediately
char g_last_good[kLineMax]; // latest displayable line, guarded by g_mtx
bool g_has_last_good = false;
bool g_has_persisted_cache = false;
TickType_t g_last_persist_tick = 0;

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

void replay_last_good()
{
    if (!g_mtx) return;
    if (xSemaphoreTake(g_mtx, portMAX_DELAY) == pdTRUE) {
        if (g_has_last_good) {
            std::snprintf(g_ready, sizeof(g_ready), "%s", g_last_good);
            g_has_ready = true;
        }
        xSemaphoreGive(g_mtx);
    }
}

bool persist_line(const char* line)
{
    nvs_handle_t handle = 0;
    esp_err_t err = nvs_open(kCacheNamespace, NVS_READWRITE, &handle);
    if (err == ESP_OK) err = nvs_set_str(handle, kCacheKey, line);
    if (err == ESP_OK) err = nvs_commit(handle);
    if (handle != 0) nvs_close(handle);
    if (err != ESP_OK) {
        mclog::tagWarn(TAG, "failed to persist stats cache: {}", esp_err_to_name(err));
        return false;
    }
    return true;
}

void load_persisted_line()
{
    nvs_handle_t handle = 0;
    esp_err_t err = nvs_open(kCacheNamespace, NVS_READONLY, &handle);
    if (err != ESP_OK) return;

    char line[kLineMax];
    size_t len = sizeof(line);
    err = nvs_get_str(handle, kCacheKey, line, &len);
    nvs_close(handle);
    if (err != ESP_OK || len <= 1 || len > sizeof(line)) return;

    if (xSemaphoreTake(g_mtx, portMAX_DELAY) == pdTRUE) {
        std::snprintf(g_last_good, sizeof(g_last_good), "%s", line);
        g_has_last_good = true;
        g_has_persisted_cache = true;
        g_last_persist_tick = xTaskGetTickCount();
        std::snprintf(g_ready, sizeof(g_ready), "%s", line);
        g_has_ready = true;
        xSemaphoreGive(g_mtx);
    }
    mclog::tagInfo(TAG, "restored cached stats");
}

// --------------------------------------------------------------------------- //
// HTTP GET (lwIP socket, HTTP/1.0 + Connection: close). Returns 0 on success
// with the response body (headers stripped) in `buf`.
// --------------------------------------------------------------------------- //
int http_get(const char* host, uint16_t port, const char* path, char* buf, int buf_size)
{
    if (!host || !path || buf_size <= 0) return -1;

    char port_str[8];
    std::snprintf(port_str, sizeof(port_str), "%u", port);

    struct addrinfo hints = {};
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo* res = nullptr;
    if (getaddrinfo(host, port_str, &hints, &res) != 0 || res == nullptr) return -1;

    int fd = socket(res->ai_family, res->ai_socktype, 0);
    if (fd < 0) {
        freeaddrinfo(res);
        return -1;
    }

    struct timeval tv = {};
    tv.tv_sec = kConnectTimeoutMs / 1000;
    tv.tv_usec = (kConnectTimeoutMs % 1000) * 1000;
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    if (connect(fd, res->ai_addr, res->ai_addrlen) != 0) {
        close(fd);
        freeaddrinfo(res);
        return -1;
    }
    freeaddrinfo(res);

    char req[256];
    int req_len = std::snprintf(req, sizeof(req),
                                "GET %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\n\r\n",
                                path, host);
    if (req_len > 0) {
        int sent = 0;
        while (sent < req_len) {
            int n = send(fd, req + sent, req_len - sent, 0);
            if (n <= 0) break;
            sent += n;
        }
    }

    int total = 0;
    ssize_t r;
    while (total < buf_size - 1 &&
           (r = recv(fd, buf + total, buf_size - 1 - total, 0)) > 0) {
        total += (int)r;
    }
    close(fd);
    if (total <= 0) return -1;
    buf[total] = '\0';

    // Strip the HTTP response headers.
    char* body = strstr(buf, "\r\n\r\n");
    if (body) {
        body += 4;
        memmove(buf, body, strlen(body) + 1);
    }
    return 0;
}

void poll_task(void*)
{
    mclog::tagInfo(TAG, "polling http://{}:{}{}", g_cfg.host, g_cfg.port, g_cfg.path);

    for (;;) {
        if (!g_active.load()) {
            vTaskDelay(pdMS_TO_TICKS(250));
            continue;
        }

        if (hub_wifi::connected() && g_cfg_set.load()) {
            char buf[kHttpGetBuf];
            if (http_get(g_cfg.host, g_cfg.port, g_cfg.path, buf, sizeof(buf)) == 0) {
                publish_line(buf, (int)strlen(buf));
            }
        }
        // Sleep in small steps so a button-triggered refresh wakes promptly.
        int32_t remaining = g_cfg.poll_ms;
        while (remaining > 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
            remaining -= 100;
            if (g_wake.exchange(false)) {
                remaining = 0;
            }
        }
    }
}

}  // namespace

namespace net {

void start(const Config& cfg)
{
    static bool task_started = false;
    if (!task_started) {
        g_cfg = cfg;
        g_mtx = xSemaphoreCreateMutex();
        if (!g_mtx) {
            mclog::tagError(TAG, "failed to allocate polling mutex");
            return;
        }

        g_cfg_set.store(true);
        load_persisted_line();

        // This worker only performs raw lwIP I/O and publishes its response to
        // RAM. NVS persistence remains on the caller's flash-safe task in
        // remember_line(), so its long-lived stack can safely live in PSRAM.
        const BaseType_t created = xTaskCreateWithCaps(
            poll_task, "cc_net", 6144, nullptr, 5, nullptr,
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (created != pdPASS) {
            mclog::tagError(TAG, "failed to allocate polling task");
            g_cfg_set.store(false);
            vSemaphoreDelete(g_mtx);
            g_mtx = nullptr;
            return;
        }
        task_started = true;
    }

    g_active.store(true);
    g_wake.store(true);
    replay_last_good();
    hub_wifi::start();
}

void suspend()
{
    g_active.store(false);
}

void request_refresh()
{
    if (g_active.load()) g_wake.store(true);
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

void remember_line(const char* line)
{
    if (!line || !g_mtx) return;
    int len = (int)strlen(line);
    if (len <= 0 || len >= kLineMax) return;

    bool should_persist = false;
    TickType_t now = xTaskGetTickCount();
    if (xSemaphoreTake(g_mtx, portMAX_DELAY) == pdTRUE) {
        bool changed = !g_has_last_good || strcmp(g_last_good, line) != 0;
        if (changed) {
            memcpy(g_last_good, line, len + 1);
            g_has_last_good = true;
            TickType_t min_interval = pdMS_TO_TICKS(kCachePersistMinIntervalMs);
            should_persist = !g_has_persisted_cache ||
                             now - g_last_persist_tick >= min_interval;
        }
        xSemaphoreGive(g_mtx);
    }

    if (should_persist && persist_line(line)) {
        if (xSemaphoreTake(g_mtx, portMAX_DELAY) == pdTRUE) {
            g_has_persisted_cache = true;
            g_last_persist_tick = now;
            xSemaphoreGive(g_mtx);
        }
    }
}

}  // namespace net
