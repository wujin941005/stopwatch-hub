/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#include "hub_wifi.h"

#include <atomic>
#include <cstdio>
#include <cstring>

#include <esp_event.h>
#include <esp_netif.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <lwip/ip4_addr.h>
#include <mooncake_log.h>
#include <nvs_flash.h>

namespace {

constexpr const char* kTag = "hub_wifi";
constexpr std::size_t kSsidSize = 33;
constexpr std::size_t kPasswordSize = 65;
constexpr std::size_t kIpSize = 16;

struct OwnedConfig {
    char ssid[kSsidSize] = {};
    char password[kPasswordSize] = {};
};

OwnedConfig g_config;
SemaphoreHandle_t g_config_mutex = nullptr;
SemaphoreHandle_t g_ip_mutex = nullptr;
SemaphoreHandle_t g_driver_mutex = nullptr;
TaskHandle_t g_service_task = nullptr;
char g_ip[kIpSize] = {};

std::atomic<bool> g_station_requested{false};
std::atomic<bool> g_exclusive_use{false};
std::atomic<bool> g_station_started{false};
std::atomic<bool> g_connected{false};

void wake_service();

bool accepted_init_result(esp_err_t result)
{
    return result == ESP_OK || result == ESP_ERR_INVALID_STATE ||
           result == ESP_ERR_WIFI_INIT_STATE;
}

OwnedConfig config_snapshot()
{
    OwnedConfig result;
    if (g_config_mutex && xSemaphoreTake(g_config_mutex, portMAX_DELAY) == pdTRUE) {
        result = g_config;
        xSemaphoreGive(g_config_mutex);
    }
    return result;
}

void set_ip(const char* ip)
{
    if (!g_ip_mutex) return;
    if (xSemaphoreTake(g_ip_mutex, portMAX_DELAY) == pdTRUE) {
        std::snprintf(g_ip, sizeof(g_ip), "%s", ip ? ip : "");
        xSemaphoreGive(g_ip_mutex);
    }
}

void on_wifi_event(void*, esp_event_base_t base, int32_t id, void* data)
{
    if (base == WIFI_EVENT) {
        switch (id) {
            case WIFI_EVENT_STA_START:
                g_station_started.store(true);
                if (!g_exclusive_use.load() && g_station_requested.load()) {
                    wake_service();
                }
                break;
            case WIFI_EVENT_STA_STOP:
                g_station_started.store(false);
                g_connected.store(false);
                set_ip("");
                break;
            case WIFI_EVENT_STA_DISCONNECTED: {
                const auto* event = static_cast<wifi_event_sta_disconnected_t*>(data);
                mclog::tagWarn(kTag, "station disconnected, reason {}", event->reason);
                g_connected.store(false);
                set_ip("");
                if (!g_exclusive_use.load() && g_station_requested.load() &&
                    g_station_started.load()) {
                    wake_service();
                }
                break;
            }
            default:
                break;
        }
        return;
    }

    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        if (g_exclusive_use.load() || !g_station_requested.load()) {
            g_connected.store(false);
            set_ip("");
            return;
        }
        const auto* event = static_cast<ip_event_got_ip_t*>(data);
        const char* ip = ip4addr_ntoa(reinterpret_cast<const ip4_addr_t*>(&event->ip_info.ip));
        set_ip(ip);
        g_connected.store(true);
        mclog::tagInfo(kTag, "station ready at {}", ip ? ip : "?");
    }
}

bool initialize_stack()
{
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        result = nvs_flash_erase();
        if (result == ESP_OK) result = nvs_flash_init();
    }
    if (result != ESP_OK) {
        mclog::tagError(kTag, "nvs init failed: {}", esp_err_to_name(result));
        return false;
    }

    result = esp_netif_init();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) {
        mclog::tagError(kTag, "netif init failed: {}", esp_err_to_name(result));
        return false;
    }

    result = esp_event_loop_create_default();
    if (result != ESP_OK && result != ESP_ERR_INVALID_STATE) {
        mclog::tagError(kTag, "event loop init failed: {}", esp_err_to_name(result));
        return false;
    }

    static esp_netif_t* station_netif = esp_netif_create_default_wifi_sta();
    if (!station_netif) {
        mclog::tagError(kTag, "failed to create station netif");
        return false;
    }

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    result = esp_wifi_init(&init_config);
    if (!accepted_init_result(result)) {
        mclog::tagError(kTag, "wifi init failed: {}", esp_err_to_name(result));
        return false;
    }

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                                on_wifi_event, nullptr));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                                on_wifi_event, nullptr));
    return true;
}

void configure_station()
{
    if (!g_station_requested.load() || g_exclusive_use.load()) return;

    // The configuration portal switches the process-wide driver to AP mode.
    // Wait for an in-flight STA transition to finish, then check ownership
    // again so a queued service wake cannot race the portal.
    if (!g_driver_mutex ||
        xSemaphoreTake(g_driver_mutex, portMAX_DELAY) != pdTRUE) {
        return;
    }
    if (!g_station_requested.load() || g_exclusive_use.load()) {
        xSemaphoreGive(g_driver_mutex);
        return;
    }

    const OwnedConfig config = config_snapshot();
    if (config.ssid[0] == '\0') {
        mclog::tagWarn(kTag, "station requested without an SSID");
        xSemaphoreGive(g_driver_mutex);
        return;
    }

    wifi_mode_t mode = WIFI_MODE_NULL;
    const bool has_mode = esp_wifi_get_mode(&mode) == ESP_OK;
    if (has_mode && mode == WIFI_MODE_STA && g_station_started.load()) {
        if (!g_connected.load()) esp_wifi_connect();
        xSemaphoreGive(g_driver_mutex);
        return;
    }

    if (g_station_started.load() || (has_mode && mode != WIFI_MODE_NULL)) {
        const esp_err_t stop_result = esp_wifi_stop();
        if (stop_result != ESP_OK && stop_result != ESP_ERR_WIFI_NOT_STARTED &&
            stop_result != ESP_ERR_WIFI_MODE) {
            mclog::tagWarn(kTag, "wifi stop failed: {}", esp_err_to_name(stop_result));
        }
    }

    wifi_config_t station_config = {};
    std::memcpy(station_config.sta.ssid, config.ssid,
                sizeof(station_config.sta.ssid));
    std::memcpy(station_config.sta.password, config.password,
                sizeof(station_config.sta.password));

    esp_err_t result = esp_wifi_set_mode(WIFI_MODE_STA);
    if (result == ESP_OK) result = esp_wifi_set_config(WIFI_IF_STA, &station_config);
    if (result == ESP_OK) result = esp_wifi_start();
    if (result != ESP_OK) {
        mclog::tagError(kTag, "station start failed: {}", esp_err_to_name(result));
        xSemaphoreGive(g_driver_mutex);
        return;
    }
    mclog::tagInfo(kTag, "connecting to '{}'", config.ssid);
    xSemaphoreGive(g_driver_mutex);
}

void service_task(void*)
{
    if (!initialize_stack()) {
        mclog::tagError(kTag, "service initialization failed");
        if (g_config_mutex &&
            xSemaphoreTake(g_config_mutex, portMAX_DELAY) == pdTRUE) {
            if (g_service_task == xTaskGetCurrentTaskHandle()) {
                g_service_task = nullptr;
            }
            xSemaphoreGive(g_config_mutex);
        }
        vTaskDelete(nullptr);
        return;
    }

    configure_station();
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        configure_station();
    }
}

void wake_service()
{
    if (!g_config_mutex ||
        xSemaphoreTake(g_config_mutex, portMAX_DELAY) != pdTRUE) {
        return;
    }
    if (g_service_task) xTaskNotifyGive(g_service_task);
    xSemaphoreGive(g_config_mutex);
}

}  // namespace

namespace hub_wifi {

void start(const Config& config)
{
    if (!g_config_mutex) g_config_mutex = xSemaphoreCreateMutex();
    if (!g_ip_mutex) g_ip_mutex = xSemaphoreCreateMutex();
    if (!g_driver_mutex) g_driver_mutex = xSemaphoreCreateMutex();
    if (!g_config_mutex || !g_ip_mutex || !g_driver_mutex) {
        mclog::tagError(kTag, "failed to allocate service mutexes");
        return;
    }

    if (xSemaphoreTake(g_config_mutex, portMAX_DELAY) == pdTRUE) {
        std::snprintf(g_config.ssid, sizeof(g_config.ssid), "%s", config.ssid ? config.ssid : "");
        std::snprintf(g_config.password, sizeof(g_config.password), "%s",
                      config.password ? config.password : "");
        xSemaphoreGive(g_config_mutex);
    }
    g_station_requested.store(true);

    if (xSemaphoreTake(g_config_mutex, portMAX_DELAY) != pdTRUE) return;
    if (!g_service_task) {
        const BaseType_t created = xTaskCreate(
            service_task, "hub_wifi", 8192, nullptr, 5, &g_service_task);
        if (created != pdPASS) {
            g_service_task = nullptr;
            mclog::tagError(kTag, "failed to create service task");
        }
        xSemaphoreGive(g_config_mutex);
        return;
    }
    xTaskNotifyGive(g_service_task);
    xSemaphoreGive(g_config_mutex);
}

bool connected()
{
    return g_connected.load();
}

bool copy_ip(char* output, std::size_t output_size)
{
    if (!output || output_size == 0 || !g_ip_mutex) return false;
    bool has_ip = false;
    if (xSemaphoreTake(g_ip_mutex, 0) == pdTRUE) {
        std::snprintf(output, output_size, "%s", g_ip);
        has_ip = g_ip[0] != '\0';
        xSemaphoreGive(g_ip_mutex);
    }
    return has_ip;
}

void suspend_for_exclusive_use()
{
    if (g_driver_mutex) {
        xSemaphoreTake(g_driver_mutex, portMAX_DELAY);
    }
    // Set the flag while holding the transition lock. Once this function
    // returns, no hub-owned STA reconfiguration can still be in flight.
    g_exclusive_use.store(true);
    g_connected.store(false);
    set_ip("");
    if (g_driver_mutex) {
        xSemaphoreGive(g_driver_mutex);
    }
}

void resume_after_exclusive_use()
{
    g_exclusive_use.store(false);
    wake_service();
}

}  // namespace hub_wifi
