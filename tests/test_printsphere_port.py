#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 wangjiacheng
# SPDX-License-Identifier: MIT

import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PORT_SCRIPT = ROOT / "scripts" / "prepare_printsphere_port.py"
SPEC = importlib.util.spec_from_file_location("prepare_printsphere_port", PORT_SCRIPT)
port = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(port)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PrintSpherePortTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.target = Path(self.tempdir.name)
        port.materialize(ROOT, self.target)
        self.upstream = ROOT / "vendor" / "PrintSphere" / "main"
        self.generated = self.target / "main" / "services" / "printsphere"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_full_include_and_source_inventory_is_preserved(self):
        expected = {
            path.relative_to(self.upstream)
            for folder in ("include", "src")
            for path in (self.upstream / folder).rglob("*")
            if path.is_file()
        }
        actual = {
            path.relative_to(self.generated)
            for path in self.generated.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, expected)

    def test_board_global_owners_are_replaced_by_hub_adapters(self):
        wifi = (self.generated / "src/wifi_manager.cpp").read_text()
        pmu = (self.generated / "src/pmu.cpp").read_text()
        audio = (self.generated / "src/audio_notifier.cpp").read_text()
        ui = (self.generated / "src/ui.cpp").read_text()
        application = (self.generated / "src/application.cpp").read_text()
        printer = (self.generated / "src/printer_client.cpp").read_text()
        cloud = (self.generated / "src/bambu_cloud_client.cpp").read_text()
        time_sync = (self.generated / "src/time_sync.cpp").read_text()

        self.assertIn("hub_wifi::configure_station", wifi)
        self.assertIn("hub_wifi::start();", wifi)
        self.assertIn("hub_wifi::copy_station_ssid", wifi)
        self.assertIn("std::string WifiManager::station_ssid() const", wifi)
        self.assertNotIn("esp_wifi_init", wifi)
        self.assertIn("GetHAL().getBatteryLevel()", pmu)
        self.assertNotIn("XPowers", pmu)
        self.assertIn("GetHAL().audioPlay", audio)
        self.assertNotIn("bsp_audio_codec_speaker_init", audio)
        self.assertIn("lv_display_get_default", ui)
        self.assertIn("lv_display_set_rotation", ui)
        self.assertNotIn("bsp_display_start_with_config", ui)
        self.assertIn("/spiflash/printsphere/sounds", application)
        self.assertIn("time_sync::start_sntp_if_needed", application)
        self.assertIn('xTaskCreateWithCaps(\n      &PrinterClient::task_entry', printer)
        self.assertIn("const esp_err_t mqtt_start_err = esp_mqtt_client_start(client_)", printer)
        self.assertIn('log_heap_status("MQTT client start failed")', printer)
        self.assertIn("start_backoff_ms", printer)
        self.assertIn("mqtt_total_failures_.fetch_add(1", printer)
        self.assertIn('xTaskCreate(&BambuCloudClient::task_entry', cloud)
        self.assertIn('"bambu_cloud", 9216', cloud)
        self.assertNotIn('xTaskCreateWithCaps', cloud)
        self.assertIn("Cloud task allocation failed", cloud)
        self.assertIn("return ESP_ERR_NO_MEM;", cloud)
        self.assertIn("hub_time::start_sntp()", time_sync)
        self.assertNotIn("ESP_NETIF_SNTP_DEFAULT_CONFIG", time_sync)
        self.assertIn("GetHAL().setTimezone(posix)", time_sync)
        self.assertIn("Timezone inherited from official device setting", time_sync)
        self.assertNotIn('setenv("TZ"', time_sync)
        self.assertNotIn("falling back to UTC", time_sync)
        self.assertIn("hub_time::time_is_trustworthy()", cloud)
        self.assertIn("Waiting for trusted network time", cloud)
        self.assertIn("http_failure_detail", cloud)
        self.assertIn("g_last_code_request_diagnostic", cloud)

    def test_mooncake_lifecycle_and_combined_ota_policy_are_present(self):
        application = (self.generated / "src/application.cpp").read_text()
        setup = (self.generated / "src/setup_portal.cpp").read_text()
        serial = (self.generated / "src/serial_provisioner.cpp").read_text()

        self.assertIn("Application::resume()", application)
        self.assertIn("Application::suspend()", application)
        self.assertIn("camera_client_.set_enabled(false)", application)
        self.assertIn('"printsphere", 9216', application)
        self.assertIn("xTaskCreatePinnedToCore", application)
        self.assertNotIn("xTaskCreatePinnedToCoreWithCaps", application)
        self.assertIn("vTaskDelete(nullptr)", application)
        self.assertIn("vTaskDelay(pdMS_TO_TICKS(3000))", application)
        self.assertIn("while (!app_active_.load())", application)
        self.assertIn("Background setup ready", application)
        self.assertIn("Reserve the flash-safe Cloud worker stack", application)
        self.assertIn("cloud_client_.set_live_mqtt_enabled(false)", application)
        self.assertLess(application.index("while (!app_active_.load())"),
                        application.index("const esp_err_t ui_err = ui_.initialize()"))
        self.assertLess(application.index("const esp_err_t cloud_start_err"),
                        application.index("wifi_manager_.initialize_network_stack()"))
        self.assertLess(application.index("const esp_err_t cloud_start_err"),
                        application.index("setup_portal_.start()"))
        self.assertNotIn("ESP_ERROR_CHECK", application)
        self.assertIn("Local MQTT worker unavailable", application)
        self.assertIn("Camera worker unavailable", application)
        self.assertIn("Web Config unavailable", application)
        self.assertNotIn("ESP_ERROR_CHECK(setup_portal_.start())", application)
        self.assertIn("config.server_port = 8080", setup)
        self.assertIn("wifi.ssid = shared_wifi_ssid", setup)
        self.assertIn("keep_active_shared_wifi", setup)
        self.assertIn("Leave empty to keep the shared device Wi-Fi password", setup)
        self.assertIn('\\"time_trusted\\"', setup)
        self.assertIn('\\"sntp_synchronized\\"', setup)
        self.assertIn('\\"sntp_started\\"', setup)
        self.assertIn('\\"sntp_last_error\\"', setup)
        self.assertIn('\\"sntp_reachability\\"', setup)
        self.assertIn('\\"internal_largest\\"', setup)
        self.assertIn('\\"psram_free\\"', setup)
        self.assertIn("official watch faces and PrintSphere", setup)
        self.assertIn(">Device default</option>", setup)
        self.assertEqual(setup.count('project_name, "StopWatch-UserDemo"'), 2)
        self.assertIn('"http://" + ip + ":8080/"', serial)

    def test_cc_island_last_good_cache_keeps_shared_wifi_and_nvs_ownership(self):
        net = (ROOT / "firmware/app_codex/net/net.cpp").read_text()
        net_header = (ROOT / "firmware/app_codex/net/net.h").read_text()
        app = (ROOT / "firmware/app_codex/app_codex.cpp").read_text()

        self.assertIn("services/hub_wifi/hub_wifi.h", net)
        self.assertIn("hub_wifi::start();", net)
        self.assertNotIn("esp_wifi_init", net)
        self.assertNotIn("esp_netif_init", net)
        self.assertNotIn("nvs_flash_init", net)
        self.assertNotIn("nvs_flash_erase", net)
        self.assertIn('kCacheNamespace = "cc_island"', net)
        self.assertIn("load_persisted_line();", net)
        self.assertIn("replay_last_good();", net)
        self.assertIn("void remember_line(const char* line)", net)
        self.assertIn("void remember_line(const char* line);", net_header)
        self.assertIn('xTaskCreateWithCaps(\n            poll_task, "cc_net", 6144', net)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", net)
        self.assertIn("if (created != pdPASS)", net)
        self.assertIn("vSemaphoreDelete(g_mtx);", net)
        self.assertEqual(net.count("if (should_persist && persist_line(line))"), 1)
        self.assertIn("has_error(codex)", app)
        self.assertIn("cJSON_IsNumber(codex_h)", app)
        self.assertIn("net::remember_line(line);", app)

    def test_installer_accepts_external_gitignored_environment(self):
        installer = (ROOT / "scripts/install_firmware.sh").read_text()
        self.assertIn("STOPWATCH_HUB_ENV_FILE", installer)
        self.assertIn('python3 - "$REPO_ROOT" "$TARGET" "$ENV_FILE"', installer)
        self.assertIn("firmware/hub_time/hub_time.cpp", installer)
        self.assertIn('("CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC", "y")', installer)
        self.assertIn('("CONFIG_SPIRAM_MALLOC_RESERVE_INTERNAL", "196608")', installer)
        self.assertIn('("CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM", "y")', installer)
        self.assertIn('("CONFIG_MQTT_TASK_STACK_ON_EXTERNAL_MEMORY", "y")', installer)
        self.assertIn('("CONFIG_MQTT_BUFFERS_ON_EXTERNAL_MEMORY", "y")', installer)
        self.assertIn('("CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP", "y")', installer)
        self.assertIn('("CONFIG_MBEDTLS_DYNAMIC_BUFFER", "y")', installer)
        self.assertIn('("CONFIG_MBEDTLS_HARDWARE_AES", None)', installer)
        self.assertIn('("CONFIG_MBEDTLS_HARDWARE_SHA", None)', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_MEM_ALLOC_MODE_EXTERNAL", "y")', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_ROLE_CENTRAL", None)', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_ROLE_OBSERVER", None)', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_SECURITY_ENABLE", None)', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_HS_PVCY", None)', installer)
        self.assertIn('("CONFIG_BT_CTRL_BLE_MASTER", "y")', installer)
        self.assertIn('("CONFIG_BT_CTRL_BLE_SCAN", None)', installer)
        self.assertIn('("CONFIG_BT_CTRL_BLE_SECURITY_ENABLE", None)', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_MAX_CONNECTIONS", "1")', installer)
        self.assertIn('("CONFIG_BT_CTRL_BLE_MAX_ACT", "2")', installer)
        self.assertIn('("CONFIG_ESP_MAIN_TASK_STACK_SIZE", "7168")', installer)
        self.assertIn('("CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE", "5120")', installer)
        self.assertIn('("CONFIG_BT_NIMBLE_HOST_TASK_STACK_SIZE", "5120")', installer)
        self.assertIn('("CONFIG_LWIP_SNTP_MAX_SERVERS", "3")', installer)
        self.assertIn('root / "sdkconfig"', installer)
        self.assertIn('rtc_driver = root / "main/hal/drivers/rx8130/rx8130.cpp"', installer)
        self.assertIn('mutating_year = "    time->tm_year -= 100;', installer)
        self.assertIn("do not mutate the caller-owned struct", installer)
        self.assertIn('lvgl_mem = root / "components/lvgl/src/stdlib/clib/lv_mem_core_clib.c"',
                      installer)
        self.assertIn("heap_caps_malloc_prefer(size, 2", installer)
        self.assertIn("heap_caps_realloc_prefer(p, new_size, 2", installer)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", installer)
        self.assertIn("MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT", installer)
        self.assertIn('m5gfx_common = root / "components/M5GFX/src/lgfx/v1/platforms/common.hpp"',
                      installer)
        self.assertIn("if (_length[_flip] < length)", installer)
        self.assertIn("auto replacement = (uint8_t*)heap_alloc_dma(length);", installer)
        self.assertIn('m5gfx_amoled = root / "components/M5GFX/src/lgfx/v1/panel/Panel_AMOLED.cpp"',
                      installer)
        self.assertIn("const size_t dma_wb = stride;", installer)
        self.assertIn("bus->getDMABuffer(dma_wb)", installer)
        self.assertIn("if (buf[0] == nullptr || buf[1] == nullptr)", installer)
        self.assertIn("expected source or patched anchor", installer)
        self.assertIn('re.sub(r"(?:#include <utility>\\n)+"', installer)
        self.assertIn('elif "step_colors" in launcher_text:', installer)
        self.assertIn('launcher_view = root / "main/apps/app_launcher/view/view.cpp"',
                      installer)
        self.assertIn("static constexpr int _loop_copies       = 3;", installer)
        self.assertIn("_icon_panels.reserve(repeated_icon_count);", installer)
        self.assertIn("_dynamic_icon_label->init(std::move(icon_label_texts)", installer)
        self.assertIn('hal_display = root / "main/hal/hal_display.cpp"', installer)
        self.assertIn('xTaskCreate(lvgl_rtos_task, "lvgl_rtos_task", 12288', installer)

    def test_cc_island_reserves_ble_before_printsphere_background_services(self):
        app = (ROOT / "firmware/app_codex/app_codex.cpp").read_text()
        ble = (ROOT / "firmware/app_codex/ble/ble_nus.cpp").read_text()
        header = (ROOT / "firmware/app_codex/ble/ble_nus.h").read_text()

        create_scope = app[app.index("void AppCodex::onCreate()"):
                           app.index("void AppCodex::onOpen()")]
        self.assertIn('ble_nus::start("CC Island");', create_scope)
        self.assertIn("bool start(const char* device_name);", header)
        self.assertIn("started = true;", ble)
        self.assertGreater(ble.index("started = true;"),
                           ble.index("nimble_port_init()"))
        self.assertNotIn("nvs_flash_erase", ble)
        self.assertNotIn("nvs_flash_init", ble)
        self.assertIn("MALLOC_CAP_INTERNAL", ble)
        self.assertIn("MALLOC_CAP_SPIRAM", ble)

    def test_hidden_printsphere_releases_live_transports_for_other_apps(self):
        application = (self.generated / "src/application.cpp").read_text()

        suspend_scope = application[application.index("void Application::suspend()"):
                                    application.index("void Application::run()")]
        self.assertIn("printer_client_.set_network_ready(false);", suspend_scope)
        self.assertIn("camera_client_.set_network_ready(false);", suspend_scope)
        self.assertIn("cloud_client_.set_live_mqtt_enabled(false);", suspend_scope)

        loop_scope = application[application.index("  while (true) {"):
                                 application.index("    const TickType_t now_tick")]
        self.assertIn("if (!app_active_.load())", loop_scope)
        self.assertIn("printer_client_.set_network_ready(false);", loop_scope)
        self.assertIn("cloud_client_.set_network_ready(", loop_scope)
        self.assertIn("vTaskDelay(pdMS_TO_TICKS(250));", loop_scope)
        self.assertIn("continue;", loop_scope)

    def test_external_mqtt_task_callbacks_do_not_write_flash_or_sleep(self):
        printer = (self.generated / "src/printer_client.cpp").read_text()
        cloud = (self.generated / "src/bambu_cloud_client.cpp").read_text()

        local_mqtt_scope = printer[
            printer.index("void PrinterClient::handle_mqtt_event"):
            printer.index("void PrinterClient::stop_client")
        ]
        cloud_event_scope = cloud[
            cloud.index("void BambuCloudClient::handle_mqtt_event"):
            cloud.index("void BambuCloudClient::stop_mqtt_client")
        ]
        cloud_report_scope = cloud[
            cloud.index("void BambuCloudClient::handle_report_payload"):
            cloud.index("void BambuCloudClient::task_entry")
        ]
        forbidden = (
            "config_store_->", "nvs_", "esp_partition_", "spi_flash_",
            "esp_restart(", "esp_deep_sleep", "esp_light_sleep",
            "fopen(", "fwrite(", "unlink(", "rename(",
        )
        for scope in (local_mqtt_scope, cloud_event_scope, cloud_report_scope):
            for token in forbidden:
                self.assertNotIn(token, scope)

    def test_external_cc_net_task_does_not_write_flash(self):
        net = (ROOT / "firmware/app_codex/net/net.cpp").read_text()
        poll_scope = net[
            net.index("void poll_task(void*)"):
            net.index("}  // namespace\n\nnamespace net")
        ]
        forbidden = (
            "persist_line(", "load_persisted_line(", "nvs_", "esp_partition_",
            "spi_flash_", "fopen(", "fwrite(", "unlink(", "rename(",
        )
        for token in forbidden:
            self.assertNotIn(token, poll_scope)

    def test_cc_screenshot_debug_storage_and_task_use_psram(self):
        source = (ROOT / "firmware/app_codex/debug/debug_screenshot.cpp").read_text()
        task_scope = source[source.index("void task(void*)"):
                            source.index("}  // namespace\n\nnamespace debug_shot")]

        self.assertIn("static uint16_t* s_row = nullptr;", source)
        self.assertIn("static char* s_b64 = nullptr;", source)
        self.assertEqual(source.count("heap_caps_malloc("), 2)
        self.assertIn('xTaskCreateWithCaps(\n        task, "cc_shot", 4096', source)
        self.assertGreater(source.index("started = true;"),
                           source.index("if (created != pdPASS)"))
        self.assertIn("heap_caps_free(s_row);", source)
        self.assertIn("MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT", source)
        for token in ("nvs_", "esp_partition_", "spi_flash_", "fopen(", "fwrite("):
            self.assertNotIn(token, task_scope)

    def test_cc_island_battery_footer_uses_factory_hal_at_low_frequency(self):
        app = (ROOT / "firmware/app_codex/app_codex.cpp").read_text()

        self.assertIn("kBatteryRefreshMs = 5000", app)
        self.assertIn("GetHAL().getBatteryLevel()", app)
        self.assertIn("GetHAL().isBatteryCharging(false)", app)
        self.assertIn("LV_SYMBOL_BATTERY_FULL", app)
        self.assertIn("LV_SYMBOL_BATTERY_EMPTY", app)
        self.assertIn("s_battery_icon_lbl = lv_label_create(s_root);", app)
        self.assertIn('charging ? "+" : ""', app)
        self.assertIn("level <= 15", app)
        self.assertIn("level <= 30", app)
        self.assertIn("s_battery_lbl = lv_label_create(s_root);", app)
        self.assertIn("s_battery_icon_lbl = nullptr;", app)
        self.assertIn("s_battery_lbl = nullptr;", app)
        self.assertLess(app.index("update_battery_label();"),
                        app.index("if (_key_manager)"))

    def test_firmware_level_time_service_owns_sntp_and_rtc_persistence(self):
        source = (ROOT / "firmware/hub_time/hub_time.cpp").read_text()
        header = (ROOT / "firmware/hub_time/hub_time.h").read_text()
        wifi = (ROOT / "firmware/hub_wifi/hub_wifi.cpp").read_text()

        self.assertIn('kNtpServerPool[] = "pool.ntp.org"', source)
        self.assertIn('kNtpServerChina[] = "ntp.aliyun.com"', source)
        self.assertIn("ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE", source)
        self.assertIn("GetHAL().syncSystemTimeToRtc()", source)
        self.assertNotIn("esp_netif_sntp_start()", source)
        self.assertIn("g_rtc_sync_pending.store(true)", source)
        self.assertIn("g_rtc_sync_pending.exchange(false)", source)
        self.assertLess(source.index("g_rtc_sync_pending.exchange(false)"),
                        source.index("GetHAL().syncSystemTimeToRtc()"))
        self.assertIn("sntp_reachability", source)
        self.assertIn("kBuildYear + 10", source)
        self.assertIn("bool time_is_trustworthy();", header)
        self.assertIn("hub_time::maintain_sntp()", wifi)
        self.assertLess(wifi.index("g_connected.store(true)"),
                        wifi.index("hub_time::maintain_sntp()"))

    def test_shared_wifi_exposes_only_the_active_ssid(self):
        header = (ROOT / "firmware/hub_wifi/hub_wifi.h").read_text()
        source = (ROOT / "firmware/hub_wifi/hub_wifi.cpp").read_text()

        self.assertIn("bool copy_station_ssid(char* output, std::size_t output_size);", header)
        self.assertIn("bool copy_station_ssid(char* output, std::size_t output_size)", source)
        self.assertNotIn("copy_station_password", header)
        self.assertNotIn("copy_station_password", source)

    def test_materialization_is_idempotent(self):
        first = tree_digest(self.generated)
        port.materialize(ROOT, self.target)
        self.assertEqual(tree_digest(self.generated), first)


if __name__ == "__main__":
    unittest.main()
