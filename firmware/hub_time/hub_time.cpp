/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#include "hub_time.h"

#include <atomic>
#include <ctime>
#include <sys/time.h>

#include <esp_log.h>
#include <esp_netif_sntp.h>
#include <hal/hal.h>
#include <mooncake_log.h>

namespace {

constexpr char kTag[] = "hub_time";
constexpr char kNtpServerPool[] = "pool.ntp.org";
constexpr char kNtpServerChina[] = "ntp.aliyun.com";
constexpr char kNtpServerFallback[] = "time.cloudflare.com";
constexpr int kBuildYear = (__DATE__[7] - '0') * 1000 + (__DATE__[8] - '0') * 100 +
                           (__DATE__[9] - '0') * 10 + (__DATE__[10] - '0');

std::atomic<bool> g_sntp_started{false};
std::atomic<bool> g_sntp_synchronized{false};
std::atomic<bool> g_rtc_sync_pending{false};
std::atomic<int> g_sntp_last_error{ESP_OK};

void on_sntp_synchronized(struct timeval*)
{
    // This callback runs on lwIP's comparatively small TCP/IP task stack.
    // Defer I2C and formatted logging to the Hub worker to avoid overflowing
    // tcpip_thread while SNTP is unwinding its receive path.
    g_sntp_synchronized.store(true);
    g_rtc_sync_pending.store(true);
}

}  // namespace

namespace hub_time {

esp_err_t start_sntp()
{
    bool expected = false;
    if (!g_sntp_started.compare_exchange_strong(expected, true)) return ESP_OK;

    esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(
        3, ESP_SNTP_SERVER_LIST(kNtpServerPool, kNtpServerChina, kNtpServerFallback));
    config.start = true;
    config.smooth_sync = false;
    config.sync_cb = &on_sntp_synchronized;
    const esp_err_t result = esp_netif_sntp_init(&config);
    g_sntp_last_error.store(result);
    if (result != ESP_OK) {
        g_sntp_started.store(false);
        mclog::tagWarn(kTag, "SNTP init failed: {}", esp_err_to_name(result));
        return result;
    }

    mclog::tagInfo(kTag, "SNTP started ({}, {}, {})", kNtpServerPool, kNtpServerChina,
                   kNtpServerFallback);
    return ESP_OK;
}

esp_err_t maintain_sntp()
{
    if (g_rtc_sync_pending.exchange(false)) {
        // RX8130 stores UTC. The stock firmware restores this value into the
        // process-wide system clock at every boot, so all launcher apps benefit.
        GetHAL().syncSystemTimeToRtc();
        mclog::tagInfo(kTag, "SNTP time persisted to RX8130 hardware RTC");
    }
    if (!g_sntp_started.load()) return start_sntp();
    // lwIP owns the retry/backoff cycle after initialization. Restarting the
    // singleton SNTP service from an application timer races its TCP/IP-thread
    // callbacks and can panic the device while another network client is live.
    return ESP_OK;
}

bool time_is_trustworthy()
{
    if (g_sntp_synchronized.load()) return true;

    // A good RX8130 value survives OTA and is usable before DNS/SNTP finishes.
    // Bound it relative to the image build year so the observed bogus 2050
    // value is rejected without hard-coding today's date forever.
    const std::time_t now = std::time(nullptr);
    struct tm utc = {};
    if (gmtime_r(&now, &utc) == nullptr) return false;
    const int year = utc.tm_year + 1900;
    return year >= kBuildYear - 1 && year <= kBuildYear + 10;
}

bool sntp_synchronized()
{
    return g_sntp_synchronized.load();
}

bool sntp_started()
{
    return g_sntp_started.load();
}

int sntp_last_error()
{
    return g_sntp_last_error.load();
}

uint8_t sntp_reachability(unsigned int server_index)
{
    unsigned int reachability = 0;
    if (esp_netif_sntp_reachability(server_index, &reachability) != ESP_OK) return 0;
    return static_cast<uint8_t>(reachability & 0xFFU);
}

}  // namespace hub_time
