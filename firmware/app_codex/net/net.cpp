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

#include <cstring>
#include <cstdio>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include <esp_wifi.h>
#include <esp_event.h>
#include <esp_netif.h>
#include <nvs_flash.h>
#include <lwip/sockets.h>
#include <lwip/netdb.h>
#include <mooncake_log.h>

using namespace net;

namespace {

constexpr const char* TAG = "net";

constexpr int kLineMax = 512;
constexpr int kHttpGetBuf = kLineMax;
constexpr int kConnectTimeoutMs = 5000;

Config g_cfg = {};
bool g_cfg_set = false;
bool g_ip_ready = false;

SemaphoreHandle_t g_mtx = nullptr;
char g_ready[kLineMax];     // last complete line, guarded by g_mtx
bool g_has_ready = false;
bool g_wake = false;        // blue button -> poll immediately

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

// --------------------------------------------------------------------------- //
// Wi-Fi events
// --------------------------------------------------------------------------- //
void on_wifi_event(void*, esp_event_base_t base, int32_t id, void* data)
{
    if (base == WIFI_EVENT) {
        switch (id) {
            case WIFI_EVENT_STA_START:
                esp_wifi_connect();
                break;
            case WIFI_EVENT_STA_DISCONNECTED: {
                wifi_event_sta_disconnected_t* e =
                    static_cast<wifi_event_sta_disconnected_t*>(data);
                mclog::tagWarn(TAG, "disconnected, reason {}", e->reason);
                g_ip_ready = false;
                esp_wifi_connect();
                break;
            }
            default:
                break;
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* e = static_cast<ip_event_got_ip_t*>(data);
        mclog::tagInfo(TAG, "got IP {}", ip4addr_ntoa((const ip4_addr_t*)&e->ip_info.ip));
        g_ip_ready = true;
    }
}

// --------------------------------------------------------------------------- //
// WiFi init + polling task.
//
// esp_wifi_init() is stack-hungry (several KB), and this runs on the Mooncake
// app task which has a small stack — so ALL the WiFi setup happens inside a
// dedicated task with a large stack. onOpen only spawns this task.
// --------------------------------------------------------------------------- //
void wifi_and_poll_task(void*)
{
    // --- Wi-Fi stack init (ignore "already initialized" errors) ---
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    if (esp_wifi_init(&wifi_cfg) != ESP_OK) {
        mclog::tagError(TAG, "esp_wifi_init failed");
        vTaskDelete(nullptr);
        return;
    }

    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, nullptr);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, nullptr);

    wifi_config_t wc = {};
    std::snprintf(reinterpret_cast<char*>(wc.sta.ssid), sizeof(wc.sta.ssid), "%s",
                  g_cfg.ssid);
    std::snprintf(reinterpret_cast<char*>(wc.sta.password), sizeof(wc.sta.password), "%s",
                  g_cfg.password);

    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wc);
    esp_wifi_start();

    mclog::tagInfo(TAG, "connecting to '{}' → http://{}:{}{}", g_cfg.ssid, g_cfg.host,
                   g_cfg.port, g_cfg.path);

    // --- poll loop ---
    vTaskDelay(pdMS_TO_TICKS(500));  // let Wi-Fi settle
    for (;;) {
        if (g_ip_ready && g_cfg_set) {
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
            if (g_wake) {
                g_wake = false;
                remaining = 0;
            }
        }
    }
}

}  // namespace

namespace net {

void start(const Config& cfg)
{
    static bool started = false;
    if (started) return;
    started = true;

    g_cfg = cfg;
    g_cfg_set = true;
    g_mtx = xSemaphoreCreateMutex();

    // Heavy WiFi init runs on this task's big stack, not the caller's.
    xTaskCreate(wifi_and_poll_task, "cc_net", 8192, nullptr, 5, nullptr);
}

void request_refresh()
{
    g_wake = true;
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

}  // namespace net
