/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#include "hub_wifi.h"
#include "hub_wifi_config.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>

#include <esp_check.h>
#include <esp_event.h>
#include <esp_netif.h>
#include <esp_wifi.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <lwip/ip4_addr.h>
#include <mooncake_log.h>
#include <nvs_flash.h>
#include <services/hub_time/hub_time.h>

namespace {

constexpr const char* kTag = "hub_wifi";
constexpr const char* kSetupIp = "192.168.4.1";
constexpr std::size_t kSsidSize = 33;
constexpr std::size_t kPasswordSize = 65;
constexpr std::size_t kIpSize = 16;
constexpr uint8_t kSetupApRetryThreshold = 3;

struct OwnedConfig {
    char ssid[kSsidSize] = {};
    char password[kPasswordSize] = {};
};

OwnedConfig g_station_config;
OwnedConfig g_setup_ap_config;
SemaphoreHandle_t g_config_mutex = nullptr;
SemaphoreHandle_t g_ip_mutex = nullptr;
SemaphoreHandle_t g_driver_mutex = nullptr;
TaskHandle_t g_service_task = nullptr;
char g_ip[kIpSize] = {};

std::atomic<int> g_stack_state{0};  // 0 starting, 1 ready, -1 failed
std::atomic<uint32_t> g_config_revision{0};
std::atomic<uint32_t> g_ap_revision{0};
std::atomic<bool> g_station_requested{false};
std::atomic<bool> g_setup_ap_requested{false};
std::atomic<bool> g_exclusive_use{false};
std::atomic<bool> g_station_started{false};
std::atomic<bool> g_ap_started{false};
std::atomic<bool> g_wifi_started{false};
std::atomic<bool> g_connected{false};
std::atomic<uint8_t> g_disconnect_retries{0};

void wake_service();

bool accepted_init_result(esp_err_t result)
{
    return result == ESP_OK || result == ESP_ERR_INVALID_STATE ||
           result == ESP_ERR_WIFI_INIT_STATE;
}

OwnedConfig config_snapshot(const OwnedConfig& source)
{
    OwnedConfig result;
    if (g_config_mutex && xSemaphoreTake(g_config_mutex, portMAX_DELAY) == pdTRUE) {
        result = source;
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
                g_wifi_started.store(true);
                wake_service();
                break;
            case WIFI_EVENT_AP_START:
                g_ap_started.store(true);
                g_wifi_started.store(true);
                wake_service();
                break;
            case WIFI_EVENT_STA_STOP:
                g_station_started.store(false);
                g_wifi_started.store(g_ap_started.load());
                g_connected.store(false);
                set_ip("");
                break;
            case WIFI_EVENT_AP_STOP:
                g_ap_started.store(false);
                g_wifi_started.store(g_station_started.load());
                break;
            case WIFI_EVENT_STA_DISCONNECTED: {
                const auto* event = static_cast<wifi_event_sta_disconnected_t*>(data);
                const uint8_t retries = static_cast<uint8_t>(g_disconnect_retries.fetch_add(1) + 1);
                mclog::tagWarn(kTag, "station disconnected, reason {}, retry {}", event ? event->reason : 0,
                               retries);
                g_connected.store(false);
                set_ip("");
                if (retries >= kSetupApRetryThreshold && g_ap_revision.load() != 0) {
                    g_setup_ap_requested.store(true);
                }
                if (!g_exclusive_use.load() && g_station_requested.load()) wake_service();
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
        g_disconnect_retries.store(0);
        g_connected.store(true);
        g_setup_ap_requested.store(false);
        // Run SNTP initialization from the Hub worker rather than the ESP-IDF
        // event task. The notification also applies the AP shutdown.
        wake_service();
        mclog::tagInfo(kTag, "station ready at {}", ip ? ip : "?");
    }
}

esp_netif_t* ensure_default_netif(const char* key, bool station)
{
    esp_netif_t* netif = esp_netif_get_handle_from_ifkey(key);
    if (netif != nullptr) return netif;
    return station ? esp_netif_create_default_wifi_sta() : esp_netif_create_default_wifi_ap();
}

bool initialize_stack()
{
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        mclog::tagError(kTag, "shared NVS requires migration; refusing to erase it");
        return false;
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

    if (!ensure_default_netif("WIFI_STA_DEF", true) ||
        !ensure_default_netif("WIFI_AP_DEF", false)) {
        mclog::tagError(kTag, "failed to create shared Wi-Fi netifs");
        return false;
    }

    wifi_init_config_t init_config = WIFI_INIT_CONFIG_DEFAULT();
    result = esp_wifi_init(&init_config);
    if (!accepted_init_result(result)) {
        mclog::tagError(kTag, "wifi init failed: {}", esp_err_to_name(result));
        return false;
    }

    result = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (result != ESP_OK) {
        mclog::tagError(kTag, "wifi RAM storage failed: {}", esp_err_to_name(result));
        return false;
    }
    result = esp_wifi_set_ps(WIFI_PS_NONE);
    if (result != ESP_OK) {
        mclog::tagWarn(kTag, "wifi power-save config failed: {}", esp_err_to_name(result));
    }

    result = esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_wifi_event, nullptr);
    if (result != ESP_OK) {
        mclog::tagError(kTag, "wifi handler registration failed: {}", esp_err_to_name(result));
        return false;
    }
    result = esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_wifi_event, nullptr);
    if (result != ESP_OK) {
        mclog::tagError(kTag, "IP handler registration failed: {}", esp_err_to_name(result));
        return false;
    }
    return true;
}

wifi_mode_t desired_mode(bool station, bool setup_ap)
{
    // Keep the station interface enabled while the setup AP is active: ESP-IDF
    // scans are a station feature, so AP-only mode would make the Web Config
    // network picker fail on a fresh device with no saved credentials.
    if (setup_ap) return WIFI_MODE_APSTA;
    if (station) return WIFI_MODE_STA;
    return WIFI_MODE_NULL;
}

template <typename Byte, std::size_t N>
std::size_t copy_wifi_field(Byte (&destination)[N], const char* source)
{
    if (!source) return 0;
    const std::size_t length = std::min(std::strlen(source), N);
    if (length > 0) std::memcpy(destination, source, length);
    return length;
}

void apply_wifi_state()
{
    if (g_stack_state.load() != 1 || g_exclusive_use.load()) return;
    if (!g_driver_mutex || xSemaphoreTake(g_driver_mutex, portMAX_DELAY) != pdTRUE) return;
    if (g_exclusive_use.load()) {
        xSemaphoreGive(g_driver_mutex);
        return;
    }

    const OwnedConfig station_config = config_snapshot(g_station_config);
    const OwnedConfig ap_config = config_snapshot(g_setup_ap_config);
    const bool station = g_station_requested.load() && station_config.ssid[0] != '\0';
    const bool setup_ap = g_setup_ap_requested.load() && ap_config.ssid[0] != '\0';
    const wifi_mode_t wanted_mode = desired_mode(station, setup_ap);
    if (wanted_mode == WIFI_MODE_NULL) {
        xSemaphoreGive(g_driver_mutex);
        return;
    }

    static uint32_t applied_config_revision = UINT32_MAX;
    static uint32_t applied_ap_revision = UINT32_MAX;
    const uint32_t config_revision = g_config_revision.load();
    const uint32_t ap_revision = g_ap_revision.load();

    wifi_mode_t current_mode = WIFI_MODE_NULL;
    const bool has_mode = esp_wifi_get_mode(&current_mode) == ESP_OK;
    esp_err_t result = ESP_OK;
    if (!has_mode || current_mode != wanted_mode) result = esp_wifi_set_mode(wanted_mode);

    if (result == ESP_OK && station && applied_config_revision != config_revision) {
        wifi_config_t config = {};
        copy_wifi_field(config.sta.ssid, station_config.ssid);
        copy_wifi_field(config.sta.password, station_config.password);
        config.sta.threshold.authmode = WIFI_AUTH_OPEN;
        config.sta.pmf_cfg.capable = true;
        config.sta.pmf_cfg.required = false;
        config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
        config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
        config.sta.bssid_set = false;
        config.sta.channel = 0;
        config.sta.failure_retry_cnt = 3;
#if CONFIG_ESP_WIFI_11KV_SUPPORT
        config.sta.rm_enabled = true;
        config.sta.btm_enabled = true;
#endif
#if CONFIG_ESP_WIFI_ENABLE_WPA3_SAE
        config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;
#endif
        result = esp_wifi_set_config(WIFI_IF_STA, &config);
        if (result == ESP_OK) applied_config_revision = config_revision;
    }

    if (result == ESP_OK && setup_ap && applied_ap_revision != ap_revision) {
        wifi_config_t config = {};
        config.ap.ssid_len = static_cast<uint8_t>(copy_wifi_field(config.ap.ssid, ap_config.ssid));
        copy_wifi_field(config.ap.password, ap_config.password);
        config.ap.channel = 1;
        config.ap.max_connection = 4;
        config.ap.authmode = ap_config.password[0] == '\0' ? WIFI_AUTH_OPEN : WIFI_AUTH_WPA2_PSK;
        config.ap.pmf_cfg.required = false;
        result = esp_wifi_set_config(WIFI_IF_AP, &config);
        if (result == ESP_OK) applied_ap_revision = ap_revision;
    }

    if (result == ESP_OK && !g_wifi_started.load()) {
        result = esp_wifi_start();
        if (result == ESP_OK) g_wifi_started.store(true);
    }
    if (result == ESP_OK && station && !g_connected.load()) {
        const esp_err_t connect_result = esp_wifi_connect();
        if (connect_result != ESP_OK && connect_result != ESP_ERR_WIFI_CONN) {
            result = connect_result;
        }
    }

    if (result != ESP_OK) {
        mclog::tagError(kTag, "apply Wi-Fi state failed: {}", esp_err_to_name(result));
    } else {
        mclog::tagInfo(kTag, "Wi-Fi mode={} station={} setup_ap={}", static_cast<int>(wanted_mode),
                       station ? 1 : 0, setup_ap ? 1 : 0);
    }
    xSemaphoreGive(g_driver_mutex);
}

void service_task(void*)
{
    if (!initialize_stack()) {
        g_stack_state.store(-1);
        mclog::tagError(kTag, "service initialization failed");
        vTaskDelete(nullptr);
        return;
    }

    g_stack_state.store(1);
    apply_wifi_state();
    for (;;) {
        const uint32_t notifications =
            ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(30000));
        if (notifications > 0) apply_wifi_state();
        if (g_connected.load()) {
            const esp_err_t time_result = hub_time::maintain_sntp();
            if (time_result != ESP_OK) {
                mclog::tagWarn(kTag, "network time maintenance failed: {}",
                               esp_err_to_name(time_result));
            }
        }
    }
}

void wake_service()
{
    if (!g_config_mutex || xSemaphoreTake(g_config_mutex, portMAX_DELAY) != pdTRUE) return;
    if (g_service_task) xTaskNotifyGive(g_service_task);
    xSemaphoreGive(g_config_mutex);
}

esp_err_t ensure_service_started()
{
    if (!g_config_mutex) g_config_mutex = xSemaphoreCreateMutex();
    if (!g_ip_mutex) g_ip_mutex = xSemaphoreCreateMutex();
    if (!g_driver_mutex) g_driver_mutex = xSemaphoreCreateMutex();
    if (!g_config_mutex || !g_ip_mutex || !g_driver_mutex) return ESP_ERR_NO_MEM;

    if (xSemaphoreTake(g_config_mutex, portMAX_DELAY) != pdTRUE) return ESP_ERR_TIMEOUT;
    if (!g_service_task) {
        g_stack_state.store(0);
        const BaseType_t created =
            xTaskCreate(service_task, "hub_wifi", 8192, nullptr, 5, &g_service_task);
        if (created != pdPASS) {
            g_service_task = nullptr;
            xSemaphoreGive(g_config_mutex);
            return ESP_ERR_NO_MEM;
        }
    }
    xSemaphoreGive(g_config_mutex);

    for (int i = 0; i < 500 && g_stack_state.load() == 0; ++i) vTaskDelay(pdMS_TO_TICKS(10));
    if (g_stack_state.load() == 1) return ESP_OK;
    return g_stack_state.load() < 0 ? ESP_FAIL : ESP_ERR_TIMEOUT;
}

}  // namespace

namespace hub_wifi {

esp_err_t initialize()
{
    return ensure_service_started();
}

void start()
{
    if (initialize() != ESP_OK) {
        mclog::tagError(kTag, "shared Wi-Fi initialization failed");
        return;
    }

    if (!configured() && kBuildConfig.ssid != nullptr && kBuildConfig.ssid[0] != '\0') {
        configure_station(kBuildConfig.ssid, kBuildConfig.password);
        return;
    }
    if (!configured()) {
        mclog::tagWarn(kTag, "Wi-Fi credentials are not configured");
        return;
    }
    g_station_requested.store(true);
    wake_service();
}

esp_err_t configure_station(const char* ssid, const char* password)
{
    if (!ssid || ssid[0] == '\0') return ESP_ERR_INVALID_ARG;
    const std::size_t ssid_length = std::strlen(ssid);
    const std::size_t password_length = password ? std::strlen(password) : 0;
    if (ssid_length > sizeof(g_station_config.ssid) - 1 ||
        password_length > sizeof(g_station_config.password) - 1) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(initialize(), kTag, "shared Wi-Fi init failed");
    if (xSemaphoreTake(g_config_mutex, portMAX_DELAY) != pdTRUE) return ESP_ERR_TIMEOUT;
    g_station_config = {};
    std::memcpy(g_station_config.ssid, ssid, ssid_length);
    if (password_length > 0) {
        std::memcpy(g_station_config.password, password, password_length);
    }
    g_config_revision.fetch_add(1);
    xSemaphoreGive(g_config_mutex);
    g_connected.store(false);
    set_ip("");
    g_station_requested.store(true);
    wake_service();
    return ESP_OK;
}

esp_err_t start_setup_access_point(const char* ssid, const char* password)
{
    if (!ssid || ssid[0] == '\0') return ESP_ERR_INVALID_ARG;
    const std::size_t ssid_length = std::strlen(ssid);
    const std::size_t password_length = password ? std::strlen(password) : 0;
    if (ssid_length > sizeof(g_setup_ap_config.ssid) - 1 ||
        password_length > sizeof(g_setup_ap_config.password) - 2 ||
        (password_length > 0 && password_length < 8)) {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(initialize(), kTag, "shared Wi-Fi init failed");
    if (xSemaphoreTake(g_config_mutex, portMAX_DELAY) != pdTRUE) return ESP_ERR_TIMEOUT;
    g_setup_ap_config = {};
    std::memcpy(g_setup_ap_config.ssid, ssid, ssid_length);
    if (password_length > 0) {
        std::memcpy(g_setup_ap_config.password, password, password_length);
    }
    g_ap_revision.fetch_add(1);
    xSemaphoreGive(g_config_mutex);
    g_setup_ap_requested.store(true);
    wake_service();
    return ESP_OK;
}

esp_err_t stop_setup_access_point()
{
    g_setup_ap_requested.store(false);
    wake_service();
    return ESP_OK;
}

bool setup_access_point_active()
{
    return g_setup_ap_requested.load() && !g_exclusive_use.load();
}

bool copy_setup_access_point_ssid(char* output, std::size_t output_size)
{
    if (!output || output_size == 0 || !g_config_mutex) return false;
    bool configured = false;
    if (xSemaphoreTake(g_config_mutex, 0) == pdTRUE) {
        std::snprintf(output, output_size, "%s", g_setup_ap_config.ssid);
        configured = g_setup_ap_config.ssid[0] != '\0';
        xSemaphoreGive(g_config_mutex);
    }
    return configured;
}

const char* setup_access_point_ip()
{
    return kSetupIp;
}

std::vector<AccessPoint> scan_visible_access_points()
{
    std::vector<AccessPoint> networks;
    if (initialize() != ESP_OK || !g_wifi_started.load() || g_exclusive_use.load()) return networks;
    if (xSemaphoreTake(g_driver_mutex, portMAX_DELAY) != pdTRUE) return networks;

    wifi_scan_config_t scan_config = {};
    scan_config.show_hidden = false;
    esp_err_t result = esp_wifi_scan_start(&scan_config, true);
    if (result != ESP_OK) {
        mclog::tagWarn(kTag, "Wi-Fi scan failed: {}", esp_err_to_name(result));
        xSemaphoreGive(g_driver_mutex);
        return networks;
    }

    uint16_t ap_count = 0;
    if (esp_wifi_scan_get_ap_num(&ap_count) == ESP_OK && ap_count > 0) {
        std::vector<wifi_ap_record_t> records(ap_count);
        uint16_t fetched = ap_count;
        if (esp_wifi_scan_get_ap_records(&fetched, records.data()) == ESP_OK) {
            std::sort(records.begin(), records.begin() + fetched,
                      [](const wifi_ap_record_t& left, const wifi_ap_record_t& right) {
                          return left.rssi > right.rssi;
                      });
            for (uint16_t i = 0; i < fetched; ++i) {
                const std::string ssid(reinterpret_cast<const char*>(records[i].ssid));
                if (ssid.empty()) continue;
                const auto existing = std::find_if(networks.begin(), networks.end(),
                                                   [&ssid](const AccessPoint& network) {
                                                       return network.ssid == ssid;
                                                   });
                if (existing == networks.end()) {
                    networks.push_back({ssid, records[i].rssi, records[i].authmode != WIFI_AUTH_OPEN});
                }
            }
        }
    }
    xSemaphoreGive(g_driver_mutex);
    return networks;
}

bool configured()
{
    if (!g_config_mutex) return false;
    bool has_config = false;
    if (xSemaphoreTake(g_config_mutex, 0) == pdTRUE) {
        has_config = g_station_config.ssid[0] != '\0';
        xSemaphoreGive(g_config_mutex);
    }
    return has_config;
}

bool connected()
{
    return g_connected.load();
}

bool copy_station_ssid(char* output, std::size_t output_size)
{
    if (!output || output_size == 0) return false;
    const OwnedConfig config = config_snapshot(g_station_config);
    std::snprintf(output, output_size, "%s", config.ssid);
    return config.ssid[0] != '\0';
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
    if (g_driver_mutex) xSemaphoreTake(g_driver_mutex, portMAX_DELAY);
    g_exclusive_use.store(true);
    g_connected.store(false);
    set_ip("");
    if (g_driver_mutex) xSemaphoreGive(g_driver_mutex);
}

void resume_after_exclusive_use()
{
    g_exclusive_use.store(false);
    wake_service();
}

}  // namespace hub_wifi
