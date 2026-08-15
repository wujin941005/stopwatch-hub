#!/usr/bin/env python3
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
  if (result == ESP_OK) netif_ready_ = wifi_ready_ = true;
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
  const BaseType_t created = xTaskCreatePinnedToCore(
      &Application::task_entry, "printsphere", 24576, this, 4, &task_handle_, 1);
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
  camera_client_.set_enabled(false);
  cloud_client_.set_preview_fetch_enabled(false);
  if (ui_ready_.load()) ui_.set_app_active(false);
}

'''
    text = replace_once(text, "void Application::run() {", lifecycle + "void Application::run() {",
                        "application lifecycle implementation")
    text = text.replace("Bootstrapping native PrintSphere project",
                        "Bootstrapping PrintSphere Mooncake app")
    text = text.replace("  ESP_ERROR_CHECK(configure_power_management());\n", "")
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
        "  ESP_ERROR_CHECK(ui_.initialize());\n"
        "  ui_ready_.store(true);\n"
        "  ui_.set_app_active(app_active_.load());\n",
        "application UI readiness",
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
    source.write_text(text)


def adapt_setup_portal(source: Path) -> None:
    text = source.read_text()
    text = replace_once(text, "  config.server_port = 80;", "  config.server_port = 8080;",
                        "PrintSphere web port")
    text = text.replace("firmware built for PrintSphere (ESP32-S3)",
                        "a StopWatch Hub combined firmware image")
    text = text.replace("firmware built for PrintSphere (ESP32-S3).",
                        "a StopWatch Hub combined firmware image.")
    text = text.replace("PrintSphere firmware image", "StopWatch Hub combined firmware image")
    text = text.replace("restart PrintSphere", "restart StopWatch Hub")
    text = text.replace("PrintSphere is rebooting", "StopWatch Hub is rebooting")
    text = text.replace(
        "https://github.com/cptkirki/PrintSphere/blob/main/release/ota/printsphere_ota.bin",
        "https://example.invalid/stopwatch-hub-ota.bin",
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
