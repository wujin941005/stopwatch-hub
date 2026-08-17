#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Cpt_Kirk
# SPDX-FileCopyrightText: 2026 wangjiacheng
# SPDX-License-Identifier: LicenseRef-FNCL-1.1

"""Materialize the pinned PrintSphere sources into a generated M5 firmware tree.

The upstream submodule stays byte-for-byte intact.  This script copies the full
v1.6.2 application into the disposable factory-firmware checkout and applies a
small, asserted adapter layer for M5Stack-owned hardware and Mooncake lifecycle.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    output, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return output


def adapt_wifi(header: Path, source: Path) -> None:
    text = header.read_text()
    text = replace_once(
        text,
        "  bool is_station_connected() const { return sta_connected_; }\n"
        "  std::string station_ip() const { return sta_ip_; }\n"
        "  bool is_setup_access_point_active() const { return setup_ap_active_; }\n"
        "  std::string setup_access_point_ssid() const { return ap_ssid_; }",
        "  bool is_station_connected() const;\n"
        "  std::string station_ssid() const;\n"
        "  std::string station_ip() const;\n"
        "  bool is_setup_access_point_active() const;\n"
        "  std::string setup_access_point_ssid() const;",
        "wifi facade declarations",
    )
    header.write_text(text)

    source.write_text(
        '''#include "printsphere/wifi_manager.hpp"

#include <cstdio>

#include "esp_log.h"
#include "printsphere/time_sync.hpp"
#include <services/hub_wifi/hub_wifi.h>

namespace printsphere {
namespace {
constexpr char kTag[] = "printsphere.wifi";
constexpr char kSetupPassword[] = "printsphere";
constexpr char kSetupApIp[] = "192.168.4.1";
}  // namespace

esp_err_t WifiManager::initialize_network_stack() {
  const esp_err_t result = hub_wifi::initialize();
  if (result == ESP_OK) {
    netif_ready_ = wifi_ready_ = true;
    // PrintSphere is created at launcher boot, while CC Island only starts
    // its transport after the user opens that app. Request the shared hub's
    // build-time station config here so a remotely flashed watch reconnects
    // without requiring a touch. An empty build config remains harmless and
    // the setup AP below still provides the provisioning fallback.
    hub_wifi::start();
  }
  return result;
}

esp_err_t WifiManager::start_setup_access_point(std::string_view device_name) {
  ap_ssid_.assign(device_name.data(), device_name.size());
  ap_ssid_.append("-Setup");
  const esp_err_t result =
      hub_wifi::start_setup_access_point(ap_ssid_.c_str(), kSetupPassword);
  setup_ap_active_ = result == ESP_OK;
  return result;
}

esp_err_t WifiManager::connect_station(const WifiCredentials& credentials) {
  if (!credentials.is_configured()) return ESP_ERR_INVALID_ARG;
  station_credentials_ = credentials;
  const esp_err_t result =
      hub_wifi::configure_station(credentials.ssid.c_str(), credentials.password.c_str());
  if (result == ESP_OK) ESP_LOGI(kTag, "Station configuration handed to hub_wifi");
  return result;
}

bool WifiManager::is_station_connected() const { return hub_wifi::connected(); }

std::string WifiManager::station_ssid() const {
  char ssid[33] = {};
  hub_wifi::copy_station_ssid(ssid, sizeof(ssid));
  return ssid;
}

std::string WifiManager::station_ip() const {
  char ip[16] = {};
  hub_wifi::copy_ip(ip, sizeof(ip));
  return ip;
}

bool WifiManager::is_setup_access_point_active() const {
  return hub_wifi::setup_access_point_active();
}

std::string WifiManager::setup_access_point_ssid() const {
  char ssid[33] = {};
  hub_wifi::copy_setup_access_point_ssid(ssid, sizeof(ssid));
  return ssid;
}

std::string WifiManager::setup_access_point_password() const { return kSetupPassword; }
std::string WifiManager::setup_access_point_ip() const { return kSetupApIp; }

std::vector<std::string> WifiManager::scan_visible_networks() const {
  std::vector<std::string> result;
  for (const auto& network : scan_visible_network_details()) result.push_back(network.ssid);
  return result;
}

std::vector<VisibleWifiNetwork> WifiManager::scan_visible_network_details() const {
  std::vector<VisibleWifiNetwork> result;
  for (const auto& network : hub_wifi::scan_visible_access_points()) {
    result.push_back({network.ssid, network.rssi, network.auth_required});
  }
  return result;
}

}  // namespace printsphere
'''
    )


def adapt_pmu(source: Path) -> None:
    source.write_text(
        '''#include "printsphere/pmu.hpp"

#include <hal/hal.h>

namespace printsphere {

esp_err_t PmuManager::initialize() {
  initialized_ = true;
  return ESP_OK;
}

PowerSnapshot PmuManager::sample() const {
  PowerSnapshot snapshot;
  if (!initialized_) return snapshot;
  snapshot.available = true;
  snapshot.battery_present = true;
  snapshot.battery_percent = GetHAL().getBatteryLevel();
  snapshot.charging = GetHAL().isBatteryCharging(false);
  snapshot.usb_present = snapshot.charging;
  return snapshot;
}

}  // namespace printsphere
'''
    )


def adapt_audio(source: Path) -> None:
    text = source.read_text()
    text = text.replace('#include "esp_codec_dev.h"\n', "")
    text = text.replace('#include "esp_codec_dev_defaults.h"\n', "")
    text = replace_regex(
        text,
        r'#if defined\(PRINTSPHERE_HW_VARIANT_AMOLED_1_75\).*?#endif\n',
        '#include <hal/hal.h>\n',
        "audio BSP include",
    )
    text = text.replace("esp_codec_dev_handle_t g_codec = nullptr;\n", "")
    worker = r'''void worker_task(void*) {
  std::vector<int16_t> note_buffer;
  std::vector<int16_t> source_pcm;
  std::vector<int16_t> output_pcm;

  uint8_t queue_item = 0;
  while (true) {
    if (xQueueReceive(g_queue, &queue_item, portMAX_DELAY) != pdTRUE) continue;
    const bool force = (queue_item & kQueueForceBit) != 0;
    const auto event = static_cast<AudioNotifier::Event>(queue_item & ~kQueueForceBit);
    const uint8_t event_idx = static_cast<uint8_t>(event);

    if (!force) {
      if (g_enabled_ptr == nullptr || !g_enabled_ptr->load(std::memory_order_relaxed)) continue;
      if (g_event_enabled_ptr != nullptr && event_idx < AudioNotifier::kEventCount &&
          !g_event_enabled_ptr[event_idx].load(std::memory_order_relaxed)) continue;
    }

    source_pcm.clear();
    if (g_pcm_mutex_ptr != nullptr && g_custom_pcm_ptr != nullptr &&
        event_idx < AudioNotifier::kEventCount) {
      std::lock_guard<std::mutex> lock(*g_pcm_mutex_ptr);
      source_pcm = g_custom_pcm_ptr[event_idx];
    }

    const int volume = g_volume_ptr != nullptr
                           ? g_volume_ptr->load(std::memory_order_relaxed)
                           : 60;
    if (custom_pcm_is_playable(source_pcm)) {
      const float scale = 0.50f * static_cast<float>(std::clamp(volume, 0, 100)) / 100.0f;
      for (int16_t& sample : source_pcm) {
        sample = static_cast<int16_t>(static_cast<int32_t>(sample) * scale);
      }
    } else {
      source_pcm.clear();
      const Melody melody = melody_for(event);
      for (uint8_t i = 0; i < melody.count; ++i) {
        render_square_tone(melody.notes[i].frequency_hz, melody.notes[i].duration_ms,
                           volume, note_buffer);
        source_pcm.insert(source_pcm.end(), note_buffer.begin(), note_buffer.end());
      }
    }

    if (source_pcm.empty()) continue;
    const int target_rate = GetHAL().getAudioSampleRate();
    if (target_rate <= 0 || target_rate == kSampleRate) {
      output_pcm = source_pcm;
    } else {
      const size_t output_count =
          source_pcm.size() * static_cast<size_t>(target_rate) / kSampleRate;
      output_pcm.resize(std::max<size_t>(1, output_count));
      for (size_t i = 0; i < output_pcm.size(); ++i) {
        const size_t source_index = std::min(
            source_pcm.size() - 1,
            i * static_cast<size_t>(kSampleRate) / static_cast<size_t>(target_rate));
        output_pcm[i] = source_pcm[source_index];
      }
    }
    GetHAL().audioPlay(output_pcm, true);
  }
}

}  // namespace

AudioNotifier::AudioNotifier'''
    text = replace_regex(
        text,
        r'void worker_task\(void\*\) \{.*?\n\}\n\n\}  // namespace\n\nAudioNotifier::AudioNotifier',
        worker,
        "audio worker",
    )
    text = replace_regex(
        text,
        r'\n  g_codec = bsp_audio_codec_speaker_init\(\);\n  if \(g_codec == nullptr\) \{.*?\n  \}\n',
        "\n",
        "audio codec initialization",
    )
    source.write_text(text)


def adapt_config_store(source: Path) -> None:
    text = source.read_text()
    text = replace_regex(
        text,
        r'esp_err_t ConfigStore::initialize\(\) \{.*?\n\}',
        '''esp_err_t ConfigStore::initialize() {
  const esp_err_t err = nvs_flash_init();
  if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_LOGE(kTag, "Shared NVS requires migration; refusing to erase official firmware settings");
    return err;
  }
  if (err == ESP_OK) {
    ESP_LOGI(kTag, "Shared NVS ready (namespace=%s)", kNamespace);
    migrate_legacy_printer_profile();
  }
  return err;
}''',
        "config NVS ownership",
    )
    text = text.replace("/sounds/snd_%u.pcm", "/spiflash/printsphere/sounds/snd_%u.pcm")
    source.write_text(text)


def adapt_background_task_stacks(printer_source: Path) -> None:
    text = printer_source.read_text()
    text = replace_once(
        text,
        '  const BaseType_t result =\n'
        '      xTaskCreate(&PrinterClient::task_entry, "printer_client", 8192, this, 5, &task_handle_);',
        '  // Keep the local MQTT worker stack out of scarce internal SRAM. Its\n'
        '  // TCB remains internal; only the explicitly permitted stack lives in PSRAM.\n'
        '  const BaseType_t result = xTaskCreateWithCaps(\n'
        '      &PrinterClient::task_entry, "printer_client", 8192, this, 5, &task_handle_,\n'
        '      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);',
        "printer task PSRAM stack",
    )
    text = replace_once(
        text,
        '''      if (esp_mqtt_client_start(client_) != ESP_OK) {
        LocalPrinterRuntimeState failed = runtime_state_copy();
        failed.connection = PrinterConnectionState::kError;
        failed.lifecycle = PrintLifecycleState::kError;
        copy_text(&failed.raw_status, "");
        copy_text(&failed.raw_stage, "");
        copy_text(&failed.stage, "mqtt-start");
        copy_text(&failed.detail, "Failed to start MQTT client");
        failed.has_error = true;
        failed.non_error_stop = false;
        failed.show_stop_banner = false;
        copy_text(&failed.resolved_serial, connection.serial);
        update_local_runtime_metadata(&failed, true, false);
        store_runtime_state(std::move(failed), false);
        publish_runtime_snapshot();
        esp_mqtt_client_destroy(client_);
        client_ = nullptr;
        vTaskDelay(pdMS_TO_TICKS(1500));
        continue;
      }''',
        '''      const esp_err_t mqtt_start_err = esp_mqtt_client_start(client_);
      if (mqtt_start_err != ESP_OK) {
        mqtt_total_failures_.fetch_add(1, std::memory_order_relaxed);
        mqtt_last_failure_ms_.store(now_ms(), std::memory_order_relaxed);
        ++consecutive_mqtt_errors_;
        const uint32_t start_backoff_ms =
            consecutive_mqtt_errors_ <= 1 ? 2000U :
            consecutive_mqtt_errors_ <= 2 ? 4000U :
            consecutive_mqtt_errors_ <= 4 ? 8000U :
            consecutive_mqtt_errors_ <= 6 ? 15000U : 30000U;
        mqtt_current_backoff_ms_.store(start_backoff_ms, std::memory_order_relaxed);
        log_heap_status("MQTT client start failed");
        ESP_LOGE(kTag, "Failed to start local MQTT client: %s; retry in %u ms",
                 esp_err_to_name(mqtt_start_err), static_cast<unsigned>(start_backoff_ms));

        LocalPrinterRuntimeState failed = runtime_state_copy();
        failed.connection = PrinterConnectionState::kError;
        failed.lifecycle = PrintLifecycleState::kError;
        copy_text(&failed.raw_status, "");
        copy_text(&failed.raw_stage, "");
        copy_text(&failed.stage, "mqtt-start");
        copy_text(&failed.detail,
                  std::string("Failed to start MQTT client: ") +
                      esp_err_to_name(mqtt_start_err));
        failed.has_error = true;
        failed.non_error_stop = false;
        failed.show_stop_banner = false;
        copy_text(&failed.resolved_serial, connection.serial);
        update_local_runtime_metadata(&failed, true, false);
        store_runtime_state(std::move(failed), false);
        publish_runtime_snapshot();
        esp_mqtt_client_destroy(client_);
        client_ = nullptr;
        vTaskDelay(pdMS_TO_TICKS(start_backoff_ms));
        continue;
      }''',
        "local MQTT start diagnostics and backoff",
    )
    printer_source.write_text(text)


def adapt_time_sync(header: Path, source: Path) -> None:
    header_text = header.read_text()
    header_text = replace_once(
        header_text,
        '// Apply the given IANA zone name (e.g. "Europe/Berlin") to the C runtime by\n'
        '// translating it to a POSIX TZ string and calling setenv("TZ", ...) + tzset().\n'
        '// An empty or unknown zone falls back to UTC. Safe to call repeatedly; the\n'
        '// new TZ takes effect for subsequent localtime_r() calls.\n',
        '// Apply the given IANA zone name (e.g. "Europe/Berlin") device-wide. The\n'
        '// matching POSIX TZ is also persisted in the official firmware settings so\n'
        '// watch faces are correct before PrintSphere starts. Empty or unknown values\n'
        '// inherit the official device timezone instead of forcing UTC.\n',
        "device-wide timezone API documentation",
    )
    header.write_text(header_text)

    text = source.read_text()
    text = replace_once(
        text,
        '#include "esp_log.h"\n'
        '#include "esp_netif_sntp.h"\n'
        '#include "esp_sntp.h"\n',
        '#include "esp_log.h"\n'
        '#include <hal/hal.h>\n'
        '#include <services/hub_time/hub_time.h>\n',
        "shared time service include",
    )
    text = replace_once(text, "bool g_sntp_started = false;\n", "",
                        "remove app-local SNTP state")
    text = replace_regex(
        text,
        r'void set_timezone_iana\(const std::string& iana_name\) \{.*?\n\}\n\n'
        r'(?=const std::string& current_iana)',
        '''void set_timezone_iana(const std::string& iana_name) {
  if (iana_name.empty()) {
    g_current_iana.clear();
    const std::string inherited = GetHAL().getTimezone();
    ESP_LOGI(kTag, "Timezone inherited from official device setting: %s",
             inherited.c_str());
    return;
  }

  const std::string posix = iana_to_posix(iana_name);
  if (posix.empty()) {
    g_current_iana.clear();
    ESP_LOGW(kTag, "Unknown IANA zone '%s'; keeping official device timezone",
             iana_name.c_str());
    return;
  }

  // Hal owns the process-wide TZ and the official firmware's system/tz NVS
  // setting. Persisting there keeps every stock watch face correct from boot.
  GetHAL().setTimezone(posix);
  g_current_iana = iana_name;
  ESP_LOGI(kTag, "Device timezone applied: %s (%s)", iana_name.c_str(), posix.c_str());
}

''',
        "persist timezone through official HAL",
    )
    text = replace_once(
        text,
        '''void start_sntp_if_needed() {
  if (g_sntp_started) {
    return;
  }
  esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
  cfg.start = true;
  cfg.smooth_sync = false;
  const esp_err_t err = esp_netif_sntp_init(&cfg);
  if (err != ESP_OK) {
    ESP_LOGW(kTag, "SNTP init failed: %s", esp_err_to_name(err));
    return;
  }
  g_sntp_started = true;
  ESP_LOGI(kTag, "SNTP started (pool.ntp.org)");
}''',
        '''void start_sntp_if_needed() {
  // Kept as a compatibility facade for upstream PrintSphere call sites. The
  // device-wide hub service owns SNTP and RX8130 persistence.
  hub_time::start_sntp();
}''',
        "delegate PrintSphere SNTP to hub",
    )
    source.write_text(text)


def adapt_bambu_cloud_client(source: Path) -> None:
    text = source.read_text()
    text = replace_once(text, "#include <cstring>\n", "#include <cstring>\n#include <ctime>\n",
                        "cloud time diagnostic include")
    text = replace_once(
        text,
        '#include "mbedtls/base64.h"\n',
        '#include "mbedtls/base64.h"\n#include <services/hub_time/hub_time.h>\n',
        "cloud shared time include",
    )
    text = replace_once(
        text,
        '''  const BaseType_t result =
      xTaskCreate(&BambuCloudClient::task_entry, "bambu_cloud", 16384, this, 4, &task_handle_);
  return result == pdPASS ? ESP_OK : ESP_FAIL;''',
        '''  const BaseType_t result =
      // Cloud HTTP/TLS and verification-code profiling peaked below 7 KiB.
      // A 9 KiB flash-safe stack keeps more than 2 KiB measured headroom while
      // returning 1 KiB of internal SRAM to Launcher/display transitions.
      xTaskCreate(&BambuCloudClient::task_entry, "bambu_cloud", 9216, this, 4, &task_handle_);
  if (result != pdPASS) {
    ESP_LOGE(kTag,
             "Cloud task allocation failed: internal=%u largest=%u psram=%u",
             static_cast<unsigned int>(
                 heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
             static_cast<unsigned int>(heap_caps_get_largest_free_block(
                 MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
             static_cast<unsigned int>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
    task_handle_ = nullptr;
    return ESP_ERR_NO_MEM;
  }
  return ESP_OK;''',
        "cloud task allocation diagnostics",
    )
    text = replace_once(
        text,
        "constexpr int kCloudPrintErrorPrintingCancelled = 0x0500400E;\n",
        "constexpr int kCloudPrintErrorPrintingCancelled = 0x0500400E;\n"
        "std::string g_last_code_request_diagnostic;\n",
        "verification request diagnostic state",
    )
    failure_detail = '''std::string http_failure_detail(const char* stage, esp_http_client_handle_t client,
                                esp_err_t primary_error) {
  const int socket_errno = client != nullptr ? esp_http_client_get_errno(client) : 0;
  int mbedtls_error = 0;
  int certificate_flags = 0;
  const esp_err_t tls_error =
      client != nullptr
          ? esp_http_client_get_and_clear_last_tls_error(
                client, &mbedtls_error, &certificate_flags)
          : ESP_FAIL;

  const std::time_t now = std::time(nullptr);
  struct tm utc = {};
  char utc_text[32] = "unavailable";
  if (gmtime_r(&now, &utc) != nullptr) {
    std::strftime(utc_text, sizeof(utc_text), "%Y-%m-%dT%H:%M:%SZ", &utc);
  }

  char detail[320] = {};
  std::snprintf(
      detail, sizeof(detail),
      "%s utc=%s esp=0x%x tls=0x%x mb=-0x%x flags=0x%x errno=%d int=%u largest=%u",
      stage != nullptr ? stage : "unknown", utc_text,
      static_cast<unsigned int>(primary_error), static_cast<unsigned int>(tls_error),
      static_cast<unsigned int>(mbedtls_error < 0 ? -mbedtls_error : mbedtls_error),
      static_cast<unsigned int>(certificate_flags), socket_errno,
      static_cast<unsigned int>(
          heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
      static_cast<unsigned int>(
          heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)));
  return detail;
}

'''
    text = replace_once(text, "void log_blob_diag(", failure_detail + "void log_blob_diag(",
                        "structured HTTP failure diagnostics")
    text = replace_once(
        text,
        '''    if (reconfigure_requested_.load() || reload_requested_.load() ||
        mqtt_auth_recovery_requested_.load()) {
      continue;
    }

    const int64_t now_us = esp_timer_get_time();''',
        '''    if (reconfigure_requested_.load() || reload_requested_.load() ||
        mqtt_auth_recovery_requested_.load()) {
      continue;
    }

    // The stock launcher restores time from RX8130. Refuse every Cloud TLS
    // path until that value is plausible or the hub-level SNTP callback has
    // corrected it; otherwise a bogus future RTC date fails certificate checks.
    if (!hub_time::time_is_trustworthy()) {
      stop_mqtt_client();
      apply_cloud_session_state(true, false, false, false,
                                "Waiting for trusted network time", false, true);
      ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000));
      continue;
    }

    const int64_t now_us = esp_timer_get_time();''',
        "cloud trusted-time gate",
    )
    text = replace_once(
        text,
        '''      if (waiting_for_user_code()) {
        apply_cloud_session_state(true, false, true, auth_mode() == AuthMode::kTfaCode,
                                  auth_mode() == AuthMode::kTfaCode
                                      ? "Bambu Cloud requires 2FA code"
                                      : "Bambu Cloud verification code required",
                                  false, true);''',
        '''      if (waiting_for_user_code()) {
        const bool phone_identity = credentials_.email.find('@') == std::string::npos;
        const std::string verification_detail =
            g_last_code_request_diagnostic.empty()
                ? (auth_mode() == AuthMode::kTfaCode
                       ? "Bambu Cloud requires 2FA code"
                       : "Bambu Cloud verification code required")
                : ((phone_identity ? "SMS" : "Email") +
                   std::string(" code request: ") + g_last_code_request_diagnostic);
        apply_cloud_session_state(true, false, true, auth_mode() == AuthMode::kTfaCode,
                                  verification_detail, false, true);''',
        "surface verification request result",
    )
    text = replace_once(
        text,
        '''    apply_cloud_session_state(true, false, false, false,
                              "Bambu Cloud login request failed", false, true);''',
        '''    apply_cloud_session_state(true, false, false, false,
                              response_body.empty()
                                  ? "Bambu Cloud login request failed"
                                  : "Bambu Cloud login request failed: " + response_body,
                              false, true);''',
        "surface login transport diagnostic",
    )
    text = replace_once(
        text,
        '''                                  : "Bambu Cloud verification code required; request a fresh code in setup portal",''',
        '''                                  : ((is_phone ? "SMS" : "Email") +
                                     std::string(" code request failed: ") +
                                     g_last_code_request_diagnostic),''',
        "surface automatic verification request failure",
    )
    for kind, label in (("email", "email"), ("SMS", "SMS")):
        failure_log = f'    ESP_LOGW(kTag, "Bambu Cloud {label}-code request failed");'
        text = replace_once(
            text,
            failure_log,
            '    g_last_code_request_diagnostic =\n'
            '        response_body.empty() ? "transport failure" : response_body;\n' + failure_log,
            f"{kind} code transport diagnostic",
        )
        rejection_log = (
            f'    ESP_LOGW(kTag, "Bambu Cloud {label}-code request rejected: status=%d body=%s", status_code,\n'
            '             response_body.c_str());'
        )
        text = replace_once(
            text,
            rejection_log,
            '    g_last_code_request_diagnostic =\n'
            '        "HTTP " + std::to_string(status_code) + " " + response_body;\n' + rejection_log,
            f"{kind} code HTTP rejection diagnostic",
        )
        success_log = f'  ESP_LOGI(kTag, "Bambu Cloud {label} code requested successfully");'
        text = replace_once(
            text,
            success_log,
            success_log + '\n  g_last_code_request_diagnostic =\n'
            '      "HTTP " + std::to_string(status_code) + " " + response_body;',
            f"{kind} code HTTP success diagnostic",
        )
    text = replace_once(
        text,
        '''  response_body->clear();
  *status_code = 0;

  esp_http_client_config_t config = {};''',
        '''  response_body->clear();
  *status_code = 0;
  if (!hub_time::time_is_trustworthy()) {
    *response_body = "stage=time system clock is not trustworthy";
    return false;
  }

  esp_http_client_config_t config = {};''',
        "JSON request trusted-time guard",
    )
    json_request_marker = "bool BambuCloudClient::perform_json_request("
    if text.count(json_request_marker) != 1:
        raise RuntimeError(
            f"JSON request diagnostic scope: expected one anchor, found "
            f"{text.count(json_request_marker)}"
        )
    before_json_request, json_request = text.split(json_request_marker, 1)
    replacements = (
        ('''  if (client == nullptr) {
    return false;
  }''',
         '''  if (client == nullptr) {
    *response_body = http_failure_detail("init", nullptr, ESP_ERR_NO_MEM);
    return false;
  }''', "HTTP init diagnostic"),
        ('''  if (open_err != ESP_OK) {
    ESP_LOGW''',
         '''  if (open_err != ESP_OK) {
    *response_body = http_failure_detail("open", client, open_err);
    ESP_LOGW''', "HTTP open diagnostic"),
        ('''    if (written < 0) {
      ESP_LOGW''',
         '''    if (written != static_cast<int>(request_body.size())) {
      *response_body = http_failure_detail("write", client, ESP_FAIL);
      ESP_LOGW''', "HTTP write diagnostic"),
        ('''  if (fetch_result < 0) {
    ESP_LOGW''',
         '''  if (fetch_result < 0) {
    *response_body = http_failure_detail("headers", client, ESP_FAIL);
    ESP_LOGW''', "HTTP headers diagnostic"),
        ('''  if (content_length > static_cast<int64_t>(kMaxJsonResponseBytes)) {
    ESP_LOGW''',
         '''  if (content_length > static_cast<int64_t>(kMaxJsonResponseBytes)) {
    *response_body = "stage=headers response_too_large=" + std::to_string(content_length);
    ESP_LOGW''', "HTTP response size diagnostic"),
        ('''    if (esp_timer_get_time() - read_start_us > kMaxReadDurationUs) {
      ESP_LOGW''',
         '''    if (esp_timer_get_time() - read_start_us > kMaxReadDurationUs) {
      *response_body = http_failure_detail("read_timeout", client, ESP_ERR_TIMEOUT);
      ESP_LOGW''', "HTTP read timeout diagnostic"),
        ('''    if (read < 0) {
      ESP_LOGW''',
         '''    if (read < 0) {
      *response_body = http_failure_detail("read", client, ESP_FAIL);
      ESP_LOGW''', "HTTP read diagnostic"),
        ('''    if (response_body->size() + static_cast<size_t>(read) > kMaxJsonResponseBytes) {
      ESP_LOGW''',
         '''    if (response_body->size() + static_cast<size_t>(read) > kMaxJsonResponseBytes) {
      *response_body = "stage=read response_exceeded_cap";
      ESP_LOGW''', "HTTP streaming size diagnostic"),
    )
    for old, new, label in replacements:
        json_request = replace_once(json_request, old, new, label)
    text = before_json_request + json_request_marker + json_request
    source.write_text(text)


def adapt_ui(header: Path, source: Path) -> None:
    text = header.read_text()
    text = replace_once(
        text,
        "  esp_err_t initialize();\n",
        "  esp_err_t initialize();\n  void set_app_active(bool active);\n",
        "UI lifecycle declaration",
    )
    for signature in (
        "  bool is_config_page_active() const {\n",
        "  bool is_page2_active() const {\n",
        "  bool is_camera_page_active() const {\n",
        "  bool is_camera_page_visible() const {\n",
        "  bool is_page_transition_active() const {\n",
    ):
        text = replace_once(text, signature, signature + "    if (!app_active_.load()) return false;\n",
                            f"UI active gate {signature.strip()}")
    text = replace_once(
        text,
        "  bool initialized_ = false;\n",
        "  bool initialized_ = false;\n"
        "  std::atomic<bool> app_active_{false};\n"
        "  int host_brightness_before_resume_ = 80;\n"
        "  uint8_t host_display_rotation_before_resume_ = 0;\n"
        "  lv_display_rotation_t host_lvgl_rotation_before_resume_ = LV_DISPLAY_ROTATION_0;\n"
        "  bool display_rotation_leased_ = false;\n",
        "UI lifecycle state",
    )
    header.write_text(text)

    text = source.read_text()
    text = replace_regex(
        text,
        r'#if defined\(PRINTSPHERE_HW_VARIANT_AMOLED_1_75\).*?#endif\n',
        '#include <hal/hal.h>\n',
        "UI BSP include",
    )
    text = text.replace("locked_ = bsp_display_lock(timeout_ms) == ESP_OK;",
                        "(void)timeout_ms;\n    locked_ = GetHAL().lvglLock();")
    text = text.replace("bsp_display_unlock();", "GetHAL().lvglUnlock();")
    text = replace_regex(
        text,
        r'bsp_display_rotation_t bsp_rotation_for\(DisplayRotation rotation\) \{.*?\n\}\n\nvoid make_transparent',
        '''lv_display_rotation_t lvgl_rotation_for(DisplayRotation rotation) {
  switch (rotation) {
    case DisplayRotation::k90:
      return LV_DISPLAY_ROTATION_90;
    case DisplayRotation::k180:
      return LV_DISPLAY_ROTATION_180;
    case DisplayRotation::k270:
      return LV_DISPLAY_ROTATION_270;
    case DisplayRotation::k0:
    default:
      return LV_DISPLAY_ROTATION_0;
  }
}

uint8_t m5_rotation_offset_for(DisplayRotation rotation) {
  return static_cast<uint8_t>(lvgl_rotation_for(rotation));
}

void make_transparent''',
        "UI BSP rotation helpers",
    )
    text = replace_regex(
        text,
        r'  bsp_display_cfg_t display_cfg = \{.*?  ESP_RETURN_ON_ERROR\(bsp_display_rotation_set\(.*?\n\n',
        '''  display_ = lv_display_get_default();
  if (display_ == nullptr) {
    ESP_LOGE(kTag, "Official LVGL display is unavailable");
    return ESP_ERR_INVALID_STATE;
  }

''',
        "UI display initialization",
    )
    text = text.replace(
        "  user_brightness_percent_ = -1;\n  applied_brightness_percent_ = -1;",
        "  user_brightness_percent_ = GetHAL().getBackLightBrightness();\n"
        "  applied_brightness_percent_ = user_brightness_percent_;",
        1,
    )
    text = text.replace("  set_brightness_percent(kDefaultBrightnessPercent);\n", "", 1)
    text = replace_once(
        text,
        "  screen_ = lv_screen_active();\n"
        "  lv_obj_set_style_bg_color(screen_, lv_color_hex(0x000000), 0);",
        "  screen_ = lv_obj_create(lv_screen_active());\n"
        "  lv_obj_set_size(screen_, board::kDisplayWidth, board::kDisplayHeight);\n"
        "  lv_obj_center(screen_);\n"
        "  lv_obj_clear_flag(screen_, LV_OBJ_FLAG_SCROLLABLE);\n"
        "  if (!app_active_.load()) lv_obj_add_flag(screen_, LV_OBJ_FLAG_HIDDEN);\n"
        "  lv_obj_set_style_border_width(screen_, 0, 0);\n"
        "  lv_obj_set_style_pad_all(screen_, 0, 0);\n"
        "  lv_obj_set_style_radius(screen_, 0, 0);\n"
        "  lv_obj_set_style_bg_color(screen_, lv_color_hex(0x000000), 0);",
        "UI app root",
    )
    text = text.replace("lv_layer_top()", "screen_")
    text = text.replace("bsp_display_brightness_set(target_brightness);",
                        "GetHAL().setBackLightBrightness(target_brightness, false);")
    text = text.replace("gpio_get_level(BSP_LCD_TOUCH_INT) == 0",
                        "GetHAL().getTouchPoint().num > 0")
    text = text.replace("    esp_lv_adapter_resume();\n", "")
    text = replace_regex(
        text,
        r'    if \(going_off && !was_off\) \{.*?    \}\n\n    apply_brightness_policy\(\);',
        '    apply_brightness_policy();',
        "UI global LVGL pause removal",
    )
    text = text.replace("\n    if (was_off && !going_off) {\n    }", "")
    lifecycle = '''void Ui::set_app_active(bool active) {
  app_active_.store(active);
  if (!initialized_ || screen_ == nullptr) return;
  LvglLockGuard lock(1000, "app_lifecycle");
  if (!lock.locked()) return;
  if (active) {
    host_brightness_before_resume_ = GetHAL().getBackLightBrightness();
    if (!display_rotation_leased_) {
      host_display_rotation_before_resume_ = GetHAL().getDisplay().getRotation();
      host_lvgl_rotation_before_resume_ = lv_display_get_rotation(display_);
      const uint8_t rotation_offset = m5_rotation_offset_for(display_rotation_);
      GetHAL().getDisplay().setRotation(
          static_cast<uint8_t>((host_display_rotation_before_resume_ + rotation_offset) & 0x03U));
      lv_display_set_rotation(
          display_,
          static_cast<lv_display_rotation_t>(
              (static_cast<uint8_t>(host_lvgl_rotation_before_resume_) + rotation_offset) & 0x03U));
      display_rotation_leased_ = true;
    }
    lv_obj_clear_flag(screen_, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(screen_);
    screen_power_mode_ = ScreenPowerMode::kAwake;
    last_activity_tick_ms_.store(lv_tick_get());
    applied_brightness_percent_ = -1;
    apply_brightness_policy();
  } else {
    lv_obj_add_flag(screen_, LV_OBJ_FLAG_HIDDEN);
    if (display_rotation_leased_) {
      GetHAL().getDisplay().setRotation(host_display_rotation_before_resume_);
      lv_display_set_rotation(display_, host_lvgl_rotation_before_resume_);
      display_rotation_leased_ = false;
      lv_obj_invalidate(lv_screen_active());
    }
    screen_power_mode_ = ScreenPowerMode::kAwake;
    applied_brightness_percent_ = -1;
    GetHAL().setBackLightBrightness(host_brightness_before_resume_, false);
  }
}

'''
    text = replace_once(text, "void Ui::set_battery_display_policy", lifecycle +
                        "void Ui::set_battery_display_policy", "UI lifecycle implementation")
    text = replace_once(
        text,
        "void Ui::update_power_save(bool on_battery, bool keep_awake, bool print_active) {\n",
        "void Ui::update_power_save(bool on_battery, bool keep_awake, bool print_active) {\n"
        "  if (!app_active_.load()) return;\n",
        "UI power lifecycle gate",
    )
    source.write_text(text)


def adapt_application(header: Path, source: Path) -> None:
    text = header.read_text()
    text = replace_once(
        text,
        "  Application();\n  void run();\n\n private:\n",
        "  Application();\n"
        "  esp_err_t start();\n"
        "  void resume();\n"
        "  void suspend();\n"
        "  bool ready() const { return ui_ready_.load(); }\n\n"
        " private:\n"
        "  static void task_entry(void* context);\n"
        "  void run();\n",
        "application lifecycle API",
    )
    text = replace_once(
        text,
        '#include "freertos/FreeRTOS.h"\n',
        '#include "freertos/FreeRTOS.h"\n#include "freertos/task.h"\n',
        "application task type include",
    )
    text = replace_once(
        text,
        "  ConfigStore config_store_{};\n",
        "  std::atomic<bool> started_{false};\n"
        "  std::atomic<bool> app_active_{false};\n"
        "  std::atomic<bool> ui_ready_{false};\n"
        "  TaskHandle_t task_handle_ = nullptr;\n"
        "  ConfigStore config_store_{};\n",
        "application lifecycle state",
    )
    header.write_text(text)

    text = source.read_text()
    for include in ('#include "driver/gpio.h"\n', '#include "esp_pm.h"\n',
                    '#include "esp_littlefs.h"\n'):
        text = text.replace(include, "")
    text = replace_regex(
        text,
        r'#if defined\(PRINTSPHERE_HW_VARIANT_AMOLED_1_75\).*?#endif\n',
        '#include <hal/hal.h>\n#include <sys/stat.h>\n',
        "application BSP include",
    )
    text = replace_regex(
        text,
        r'esp_err_t configure_power_management\(\) \{.*?\n\}\n\n',
        "",
        "application power ownership",
    )
    text = text.replace("gpio_get_level(BSP_LCD_TOUCH_INT) == 0",
                        "GetHAL().getTouchPoint().num > 0")
    lifecycle = '''esp_err_t Application::start() {
  bool expected = false;
  if (!started_.compare_exchange_strong(expected, true)) return ESP_OK;
  // This task performs FAT and NVS operations while the flash cache can be
  // disabled, so its stack must remain in internal RAM. Real-device Cloud,
  // local MQTT and full-UI profiling peaked below 7 KiB; 9 KiB preserves more
  // than 2.5 KiB measured headroom and returns another KiB to
  // DMA/launcher transitions.
  const BaseType_t created = xTaskCreatePinnedToCore(
      &Application::task_entry, "printsphere", 9216, this, 4, &task_handle_, 1);
  if (created != pdPASS) {
    task_handle_ = nullptr;
    started_.store(false);
    return ESP_ERR_NO_MEM;
  }
  return ESP_OK;
}

void Application::task_entry(void* context) {
  auto* application = static_cast<Application*>(context);
  if (application != nullptr) application->run();
  vTaskDelete(nullptr);
}

void Application::resume() {
  app_active_.store(true);
  if (ui_ready_.load()) ui_.set_app_active(true);
}

void Application::suspend() {
  app_active_.store(false);
  // The Web Config and cloud-provisioning worker remain process-lifetime, but
  // the live printer transports belong to the foreground App. Drop local MQTT
  // immediately so opening the stock launcher or CC Island gets its TLS/UI
  // heap back before allocating another screen.
  printer_client_.set_network_ready(false);
  camera_client_.set_network_ready(false);
  camera_client_.set_enabled(false);
  cloud_client_.set_live_mqtt_enabled(false);
  cloud_client_.set_preview_fetch_enabled(false);
  if (ui_ready_.load()) ui_.set_app_active(false);
}

'''
    text = replace_once(text, "void Application::run() {", lifecycle + "void Application::run() {",
                        "application lifecycle implementation")
    text = text.replace("Bootstrapping native PrintSphere project",
                        "Bootstrapping PrintSphere Mooncake app")
    text = replace_once(
        text,
        '  ESP_LOGI(kTag, "Bootstrapping PrintSphere Mooncake app");\n',
        '  ESP_LOGI(kTag, "Bootstrapping PrintSphere Mooncake app");\n'
        '  // Mooncake creates every App before it finishes constructing the stock\n'
        '  // launcher and status bar. Let that foreground boot path settle before\n'
        '  // starting the background Wi-Fi/Web Config services.\n'
        '  vTaskDelay(pdMS_TO_TICKS(3000));\n',
        "application launcher boot grace",
    )
    text = text.replace("  ESP_ERROR_CHECK(configure_power_management());\n", "")
    text = replace_once(
        text,
        "  ESP_ERROR_CHECK(config_store_.initialize());\n",
        "  const esp_err_t config_err = config_store_.initialize();\n"
        "  if (config_err != ESP_OK) {\n"
        "    ESP_LOGE(kTag, \"Config unavailable; leaving official launcher running: %s\",\n"
        "             esp_err_to_name(config_err));\n"
        "    return;\n"
        "  }\n",
        "nonfatal config bootstrap",
    )
    text = replace_once(
        text,
        "  ESP_ERROR_CHECK(wifi_manager_.initialize_network_stack());\n"
        "  ESP_ERROR_CHECK(wifi_manager_.start_setup_access_point(config_store_.load_device_name()));\n",
        "  const esp_err_t wifi_stack_err = wifi_manager_.initialize_network_stack();\n"
        "  if (wifi_stack_err != ESP_OK) {\n"
        "    ESP_LOGE(kTag, \"Wi-Fi unavailable; leaving official launcher running: %s\",\n"
        "             esp_err_to_name(wifi_stack_err));\n"
        "    return;\n"
        "  }\n"
        "  const esp_err_t setup_ap_err =\n"
        "      wifi_manager_.start_setup_access_point(config_store_.load_device_name());\n"
        "  if (setup_ap_err != ESP_OK) {\n"
        "    ESP_LOGW(kTag, \"Setup AP unavailable; station Web Config may still work: %s\",\n"
        "             esp_err_to_name(setup_ap_err));\n"
        "  }\n",
        "nonfatal Wi-Fi bootstrap",
    )
    early_cloud_bootstrap = '''  // Reserve the flash-safe Cloud worker stack before Wi-Fi and Web Config
  // fragment internal SRAM. The worker remains network-gated until the shared
  // station is ready, so this changes allocation order without starting Cloud
  // traffic during the official launcher boot.
  const BambuCloudCredentials cloud_credentials = config_store_.load_cloud_credentials();
  source_mode_ = config_store_.load_source_mode();
  const PrinterConnection printer_connection =
      config_store_.load_active_printer_profile().to_connection();
  cloud_client_.configure(cloud_credentials, printer_connection.serial);
  const esp_err_t cloud_start_err = cloud_client_.start();
  if (cloud_start_err != ESP_OK) {
    ESP_LOGE(kTag, "Bambu Cloud worker unavailable: %s", esp_err_to_name(cloud_start_err));
  }

'''
    text = replace_once(
        text,
        "  // Apply persisted timezone before any localtime_r() consumer (UI ETA,\n",
        early_cloud_bootstrap +
        "  // Apply persisted timezone before any localtime_r() consumer (UI ETA,\n",
        "reserve cloud worker before network services",
    )
    text = replace_once(
        text,
        "  ESP_ERROR_CHECK(pmu_manager_.initialize());\n",
        "  const esp_err_t pmu_err = pmu_manager_.initialize();\n"
        "  if (pmu_err != ESP_OK) {\n"
        "    ESP_LOGW(kTag, \"PrintSphere battery telemetry unavailable: %s\",\n"
        "             esp_err_to_name(pmu_err));\n"
        "  }\n",
        "nonfatal PMU bootstrap",
    )
    text = replace_regex(
        text,
        r'  // Mount the LittleFS partition that holds custom sound files\..*?\n  \}\n\n  // Per-event',
        '''  // The official firmware already mounted its FAT volume. Keep all
  // PrintSphere-owned files below one directory and never mount a second FS.
  mkdir("/spiflash/printsphere", 0755);
  mkdir("/spiflash/printsphere/sounds", 0755);

  // Per-event''',
        "application shared FAT storage",
    )
    text = replace_once(
        text,
        "  ESP_ERROR_CHECK(ui_.initialize());\n",
        "  const esp_err_t ui_err = ui_.initialize();\n"
        "  if (ui_err != ESP_OK) {\n"
        "    ESP_LOGE(kTag, \"PrintSphere UI unavailable; close the App to return home: %s\",\n"
        "             esp_err_to_name(ui_err));\n"
        "    app_active_.store(false);\n"
        "    return;\n"
        "  }\n"
        "  ui_ready_.store(true);\n"
        "  ui_.set_app_active(app_active_.load());\n",
        "application UI readiness",
    )
    cloud_bootstrap = '''  // Keep remote provisioning available while PrintSphere sleeps in the
  // launcher. Cloud password login, email/2FA verification and printer binding
  // work through Web Config, but live MQTT and preview traffic stay dormant.
  // The full dashboard/audio/camera/local-MQTT runtime is materialized only
  // after Mooncake calls resume() from AppPrintSphere::onOpen().
  ESP_LOGI(kTag, "Background setup ready; waiting for PrintSphere App open");
  while (!app_active_.load()) {
    const bool setup_wifi_connected = wifi_manager_.is_station_connected();
    if (setup_wifi_connected && !last_wifi_connected_) {
      time_sync::start_sntp_if_needed();
    }
    source_mode_ = config_store_.load_source_mode();
    cloud_client_.set_network_ready(setup_wifi_connected && source_mode_ != SourceMode::kLocalOnly);
    cloud_client_.set_live_mqtt_enabled(false);
    cloud_client_.set_preview_fetch_enabled(false);
    cloud_client_.set_fetch_paused(false);
    last_wifi_connected_ = setup_wifi_connected;
    vTaskDelay(pdMS_TO_TICKS(250));
  }
  ESP_LOGI(kTag, "PrintSphere App opened; starting full runtime");

'''
    text = replace_once(
        text,
        "  ui_.set_arc_color_scheme(config_store_.load_arc_color_scheme());\n",
        cloud_bootstrap +
        "  ui_.set_arc_color_scheme(config_store_.load_arc_color_scheme());\n",
        "background provisioning before lazy UI",
    )
    text = replace_once(
        text,
        "  while (true) {\n"
        "    const TickType_t now_tick = xTaskGetTickCount();\n",
        "  while (true) {\n"
        "    if (!app_active_.load()) {\n"
        "      // Keep Wi-Fi and Web Config reachable, but do not let hidden UI,\n"
        "      // local MQTT, camera, or cloud MQTT compete with another App.\n"
        "      const bool setup_wifi_connected = wifi_manager_.is_station_connected();\n"
        "      if (setup_wifi_connected && !last_wifi_connected_) {\n"
        "        time_sync::start_sntp_if_needed();\n"
        "      }\n"
        "      source_mode_ = config_store_.load_source_mode();\n"
        "      printer_client_.set_network_ready(false);\n"
        "      camera_client_.set_network_ready(false);\n"
        "      camera_client_.set_enabled(false);\n"
        "      cloud_client_.set_network_ready(\n"
        "          setup_wifi_connected && source_mode_ != SourceMode::kLocalOnly);\n"
        "      cloud_client_.set_live_mqtt_enabled(false);\n"
        "      cloud_client_.set_preview_fetch_enabled(false);\n"
        "      cloud_client_.set_fetch_paused(false);\n"
        "      last_wifi_connected_ = setup_wifi_connected;\n"
        "      vTaskDelay(pdMS_TO_TICKS(250));\n"
        "      continue;\n"
        "    }\n"
        "    const TickType_t now_tick = xTaskGetTickCount();\n",
        "inactive foreground transport gate",
    )
    text = replace_once(
        text,
        "  const BambuCloudCredentials cloud_credentials = config_store_.load_cloud_credentials();\n"
        "  source_mode_ = config_store_.load_source_mode();\n"
        "  const PrinterConnection printer_connection = config_store_.load_active_printer_profile().to_connection();\n"
        "  cloud_client_.configure(cloud_credentials, printer_connection.serial);\n"
        "  ESP_ERROR_CHECK(cloud_client_.start());\n\n",
        "",
        "remove eager duplicate cloud bootstrap",
    )
    text = replace_once(
        text,
        "    const bool wifi_connected = wifi_manager_.is_station_connected();\n",
        "    const bool wifi_connected = wifi_manager_.is_station_connected();\n"
        "    if (wifi_connected && !last_wifi_connected_) {\n"
        "      time_sync::start_sntp_if_needed();\n"
        "    }\n",
        "application SNTP transition",
    )
    text = replace_once(
        text,
        "  printer_client_.configure(printer_connection);\n"
        "  ESP_ERROR_CHECK(printer_client_.start());\n"
        "  camera_client_.configure(printer_connection);\n"
        "  ESP_ERROR_CHECK(camera_client_.start());\n",
        "  printer_client_.configure(printer_connection);\n"
        "  const esp_err_t printer_start_err = printer_client_.start();\n"
        "  if (printer_start_err != ESP_OK) {\n"
        "    ESP_LOGE(kTag, \"Local MQTT worker unavailable: %s\",\n"
        "             esp_err_to_name(printer_start_err));\n"
        "  }\n"
        "  camera_client_.configure(printer_connection);\n"
        "  const esp_err_t camera_start_err = camera_client_.start();\n"
        "  if (camera_start_err != ESP_OK) {\n"
        "    ESP_LOGE(kTag, \"Camera worker unavailable: %s\",\n"
        "             esp_err_to_name(camera_start_err));\n"
        "  }\n",
        "nonfatal optional workers",
    )
    text = replace_once(
        text,
        "  ESP_ERROR_CHECK(setup_portal_.start());",
        '''  ESP_LOGI(kTag, "Before Web Config: internal_free=%u largest_internal=%u psram_free=%u",
           static_cast<unsigned int>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
           static_cast<unsigned int>(
               heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
           static_cast<unsigned int>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));
  const esp_err_t portal_err = setup_portal_.start();
  if (portal_err != ESP_OK) {
    // A Web Config allocation failure must not turn the entire official
    // launcher into a reboot loop. Keep the remaining PrintSphere runtime
    // alive so the device stays locally recoverable and can be reflashed.
    ESP_LOGE(kTag, "Web Config unavailable: %s", esp_err_to_name(portal_err));
  }''',
        "non-fatal Web Config startup",
    )
    source.write_text(text)


def adapt_setup_portal(source: Path) -> None:
    text = source.read_text()
    text = replace_once(text, "#include <cstring>\n", "#include <cstring>\n#include <ctime>\n",
                        "portal time diagnostic include")
    text = replace_once(
        text,
        '#include "esp_https_ota.h"\n',
        '#include "esp_https_ota.h"\n#include "esp_heap_caps.h"\n',
        "portal heap diagnostic include",
    )
    text = replace_once(
        text,
        '#include "printsphere/ui.hpp"\n',
        '#include "printsphere/ui.hpp"\n#include <services/hub_time/hub_time.h>\n',
        "portal shared time include",
    )
    text = replace_once(text, "  config.server_port = 80;", "  config.server_port = 8080;",
                        "PrintSphere web port")
    text = text.replace("firmware built for PrintSphere (ESP32-S3)",
                        "a StopWatch Hub combined firmware image")
    text = text.replace("firmware built for PrintSphere (ESP32-S3).",
                        "a StopWatch Hub combined firmware image.")
    text = text.replace("PrintSphere firmware image", "StopWatch Hub combined firmware image")
    text = text.replace("restart PrintSphere", "restart StopWatch Hub")
    text = text.replace("PrintSphere is rebooting", "StopWatch Hub is rebooting")
    text = replace_once(
        text,
        'const std::string tz_badge_value = saved_tz.empty() ? "Auto" : saved_tz;',
        'const std::string tz_badge_value = saved_tz.empty() ? "Device" : saved_tz;',
        "timezone inherited badge",
    )
    text = replace_once(
        text,
        '"Local time used for the on-screen ETA. Auto-detected from your browser when unset.",',
        '"Local time used across official watch faces and PrintSphere. Your browser timezone is pre-selected when unset.",',
        "device-wide timezone description",
    )
    text = replace_once(text, '>Auto (browser)</option>', '>Device default</option>',
                        "timezone default option")
    text = replace_once(
        text,
        "'Local time is now '+(tz_iana||'UTC')+'.'",
        "'Local time is now '+(tz_iana||'the device default')+'.'",
        "timezone apply status",
    )
    text = text.replace(
        "https://github.com/cptkirki/PrintSphere/blob/main/release/ota/printsphere_ota.bin",
        "https://example.invalid/stopwatch-hub-ota.bin",
    )
    health_diagnostics = '''    const std::time_t system_time = std::time(nullptr);
    struct tm system_utc = {};
    char system_utc_text[32] = "unavailable";
    if (gmtime_r(&system_time, &system_utc) != nullptr) {
      std::strftime(system_utc_text, sizeof(system_utc_text), "%Y-%m-%dT%H:%M:%SZ",
                    &system_utc);
    }
    body += ",\\\"uptime_ms\\\":" + std::to_string(now_ms());
    body += ",\\\"reset_reason\\\":" + std::to_string(static_cast<int>(esp_reset_reason()));
    body += ",\\\"system_unix_time\\\":" + std::to_string(system_time);
    body += ",\\\"system_utc\\\":\\\"" + json_escape(system_utc_text) + "\\\"";
    body += ",\\\"time_trusted\\\":";
    body += hub_time::time_is_trustworthy() ? "true" : "false";
    body += ",\\\"sntp_synchronized\\\":";
    body += hub_time::sntp_synchronized() ? "true" : "false";
    body += ",\\\"sntp_started\\\":";
    body += hub_time::sntp_started() ? "true" : "false";
    body += ",\\\"sntp_last_error\\\":" + std::to_string(hub_time::sntp_last_error());
    body += ",\\\"sntp_reachability\\\":[" +
            std::to_string(hub_time::sntp_reachability(0)) + "," +
            std::to_string(hub_time::sntp_reachability(1)) + "," +
            std::to_string(hub_time::sntp_reachability(2)) + "]";
    body += ",\\\"internal_free\\\":" + std::to_string(
        heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    body += ",\\\"internal_largest\\\":" + std::to_string(
        heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    body += ",\\\"psram_free\\\":" + std::to_string(
        heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    body += ",\\\"psram_largest\\\":" + std::to_string(
        heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
'''
    text = replace_once(
        text,
        '''  if (request_authorized) {
    body += ",\\\"source_mode\\\":\\\"";''',
        '''  if (request_authorized) {
''' + health_diagnostics + '''    body += ",\\\"source_mode\\\":\\\"";''',
        "authorized time and memory health diagnostics",
    )
    effective_wifi = '''  WifiCredentials wifi = portal->config_store_.load_wifi_credentials();
  const std::string shared_wifi_ssid = portal->wifi_manager_.station_ssid();
  if (!shared_wifi_ssid.empty() && shared_wifi_ssid != wifi.ssid) {
    // hub_wifi is device-wide and may currently be using the build-time
    // fallback. Show that real selection without exposing its password.
    wifi.ssid = shared_wifi_ssid;
    wifi.password.clear();
  }'''
    wifi_load_anchor = (
        "  const WifiCredentials wifi = portal->config_store_.load_wifi_credentials();"
    )
    wifi_load_count = text.count(wifi_load_anchor)
    if wifi_load_count != 2:
        raise RuntimeError(
            f"effective shared Wi-Fi views: expected two anchors, found {wifi_load_count}"
        )
    text = text.replace(wifi_load_anchor, effective_wifi, 2)
    text = replace_once(
        text,
        '''  const std::string wifi_password_placeholder =
      wifi_password_saved ? "Leave empty to keep saved Wi-Fi password" : "Enter Wi-Fi password";''',
        '''  const bool wifi_uses_shared_station =
      !wifi.ssid.empty() && wifi.ssid == shared_wifi_ssid;
  const std::string wifi_password_placeholder =
      wifi_password_saved
          ? "Leave empty to keep saved Wi-Fi password"
          : (wifi_uses_shared_station
                 ? "Leave empty to keep the shared device Wi-Fi password"
                 : "Enter Wi-Fi password");''',
        "shared Wi-Fi password placeholder",
    )
    text = replace_once(
        text,
        '''  const WifiCredentials wifi = merge_wifi_credentials({
      .ssid = trim_copy(read_string_field(root, "wifi_ssid")),
      .password = read_string_field(root, "wifi_password"),
  }, stored_wifi);''',
        '''  const std::string shared_wifi_ssid = portal->wifi_manager_.station_ssid();
  const WifiCredentials submitted_wifi = {
      .ssid = trim_copy(read_string_field(root, "wifi_ssid")),
      .password = read_string_field(root, "wifi_password"),
  };
  // A build-time/shared station password is intentionally unreadable. If the
  // form merely reflects that SSID and leaves the password blank, retain the
  // active shared configuration instead of persisting an empty password.
  const bool keep_active_shared_wifi =
      submitted_wifi.password.empty() && !shared_wifi_ssid.empty() &&
      submitted_wifi.ssid == shared_wifi_ssid && stored_wifi.ssid != shared_wifi_ssid;
  const WifiCredentials wifi = keep_active_shared_wifi
                                   ? submitted_wifi
                                   : merge_wifi_credentials(submitted_wifi, stored_wifi);''',
        "preserve active shared Wi-Fi submission",
    )
    text = replace_once(
        text,
        '  ESP_RETURN_ON_ERROR(portal->config_store_.save_wifi_credentials(wifi), kTag, "save wifi failed");',
        '''  if (!keep_active_shared_wifi) {
    ESP_RETURN_ON_ERROR(portal->config_store_.save_wifi_credentials(wifi), kTag,
                        "save wifi failed");
  }''',
        "skip unchanged shared Wi-Fi persistence",
    )
    validation = '''
  esp_app_desc_t uploaded_app = {};
  err = esp_ota_get_partition_description(update_partition, &uploaded_app);
  if (err != ESP_OK || std::strcmp(uploaded_app.project_name, "StopWatch-UserDemo") != 0) {
    ESP_LOGE(kTag, "Rejected non-Hub OTA image (project=%s)", uploaded_app.project_name);
    httpd_resp_set_status(request, "422 Unprocessable Entity");
    send_json(request,
              "{\\\"error\\\":\\\"Wrong firmware\\\",\\\"detail\\\":\\\"Only a StopWatch Hub combined OTA image is accepted.\\\"}");
    return ESP_OK;
  }

'''
    text = replace_once(
        text,
        "  err = esp_ota_set_boot_partition(update_partition);",
        validation + "  err = esp_ota_set_boot_partition(update_partition);",
        "uploaded OTA project validation",
    )
    url_validation = '''
  esp_app_desc_t remote_app = {};
  err = esp_https_ota_get_img_desc(ota_handle, &remote_app);
  if (err != ESP_OK || std::strcmp(remote_app.project_name, "StopWatch-UserDemo") != 0) {
    ESP_LOGE(kTag, "Rejected non-Hub OTA URL image (project=%s)", remote_app.project_name);
    esp_https_ota_abort(ota_handle);
    {
      std::lock_guard<std::mutex> lock(portal->ota_url_mutex_);
      portal->ota_url_status_.state = OtaUrlState::kFailed;
      portal->ota_url_status_.error = "Only StopWatch Hub combined firmware is accepted";
    }
    vTaskDelete(nullptr);
    return;
  }

'''
    text = replace_once(
        text,
        "  while (true) {\n    err = esp_https_ota_perform(ota_handle);",
        url_validation + "  while (true) {\n    err = esp_https_ota_perform(ota_handle);",
        "URL OTA project validation",
    )
    source.write_text(text)


def adapt_serial_provisioner(source: Path) -> None:
    text = source.read_text()
    text = replace_once(
        text,
        '  return ip.empty() ? std::string{} : "http://" + ip + "/";',
        '  return ip.empty() ? std::string{} : "http://" + ip + ":8080/";',
        "Improv Serial device URL",
    )
    source.write_text(text)


def materialize(repo: Path, target: Path) -> None:
    upstream = repo / "vendor" / "PrintSphere" / "main"
    if not (upstream / "src" / "application.cpp").exists():
        raise RuntimeError("PrintSphere submodule is missing; run git submodule update --init")

    destination = target / "main" / "services" / "printsphere"
    legacy_core = target / "main" / "services" / "printsphere_core"
    if legacy_core.exists():
        shutil.rmtree(legacy_core)
    if destination.exists():
        shutil.rmtree(destination)
    (destination / "include").mkdir(parents=True)
    shutil.copytree(upstream / "include", destination / "include", dirs_exist_ok=True)
    shutil.copytree(upstream / "src", destination / "src", dirs_exist_ok=True)

    adapt_wifi(destination / "include/printsphere/wifi_manager.hpp",
               destination / "src/wifi_manager.cpp")
    adapt_pmu(destination / "src/pmu.cpp")
    adapt_audio(destination / "src/audio_notifier.cpp")
    adapt_config_store(destination / "src/config_store.cpp")
    adapt_background_task_stacks(destination / "src/printer_client.cpp")
    adapt_time_sync(destination / "include/printsphere/time_sync.hpp",
                    destination / "src/time_sync.cpp")
    adapt_bambu_cloud_client(destination / "src/bambu_cloud_client.cpp")
    adapt_ui(destination / "include/printsphere/ui.hpp", destination / "src/ui.cpp")
    adapt_application(destination / "include/printsphere/application.hpp",
                      destination / "src/application.cpp")
    adapt_setup_portal(destination / "src/setup_portal.cpp")
    adapt_serial_provisioner(destination / "src/serial_provisioner.cpp")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    materialize(args.repo.resolve(), args.target.resolve())
    print("   full PrintSphere v1.6.2 source + M5 adapters materialized")


if __name__ == "__main__":
    main()
