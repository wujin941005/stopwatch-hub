#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 wangjiacheng
# SPDX-License-Identifier: MIT
#
# Integrate the StopWatch Hub apps into a fresh M5Stack StopWatch
# factory-firmware checkout, then build + flash with ESP-IDF.
#
# Usage:
#   scripts/install_firmware.sh [TARGET_DIR]
#
# TARGET_DIR defaults to ./build-firmware (gitignored). Safe to re-run; every
# edit below is idempotent.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-$REPO_ROOT/build-firmware}"
ENV_FILE="${STOPWATCH_HUB_ENV_FILE:-$REPO_ROOT/.env}"
FACTORY_GIT="https://github.com/m5stack/M5StopWatch-UserDemo.git"
FACTORY_TAG="V0.5"
FACTORY_COMMIT="6b4aa125288b6fe9dca661f10159f6e1e5ee785c"

echo "==> StopWatch Hub firmware integration"
echo "    repo:   $REPO_ROOT"
echo "    target: $TARGET"

# 1. Clone the factory firmware (MIT, by M5Stack) if not already present.
if [ ! -d "$TARGET/.git" ]; then
  echo "==> Cloning factory firmware..."
  git clone --branch "$FACTORY_TAG" --single-branch "$FACTORY_GIT" "$TARGET"
fi

FACTORY_HEAD="$(git -C "$TARGET" rev-parse HEAD)"
if [ "$FACTORY_HEAD" != "$FACTORY_COMMIT" ]; then
  echo "WARNING: factory checkout is $FACTORY_HEAD, validated commit is $FACTORY_COMMIT"
  echo "         Existing checkouts are never reset automatically."
fi

# 2. Fetch the firmware's component dependencies (M5GFX, lvgl, mooncake, ...).
#    The opt-out is useful for a copied, already-populated offline build tree.
if [ "${STOPWATCH_HUB_SKIP_FETCH:-0}" = "1" ]; then
  echo "==> Skipping firmware dependency fetch (STOPWATCH_HUB_SKIP_FETCH=1)"
else
  echo "==> Fetching firmware dependencies..."
  ( cd "$TARGET" && python3 ./fetch_repos.py )
fi

# 3. Drop in both apps, the complete pinned PrintSphere source/adapter layer,
#    shared services, and launcher assets.
echo "==> Copying StopWatch Hub apps, services, platform adapters, and assets..."
mkdir -p "$TARGET/main/apps/app_codex/ble" \
         "$TARGET/main/apps/app_codex/net" \
         "$TARGET/main/apps/app_codex/debug" \
         "$TARGET/main/apps/app_printsphere" \
         "$TARGET/main/services/hub_wifi" \
         "$TARGET/main/services/hub_time" \
         "$TARGET/main/platform/printsphere_m5" \
         "$TARGET/main/assets/images"
cp "$REPO_ROOT"/firmware/app_codex/app_codex.h          "$TARGET/main/apps/app_codex/"
cp "$REPO_ROOT"/firmware/app_codex/app_codex.cpp        "$TARGET/main/apps/app_codex/"
cp "$REPO_ROOT"/firmware/app_codex/app_codex_config.h   "$TARGET/main/apps/app_codex/"
cp "$REPO_ROOT"/firmware/app_codex/ble/ble_nus.h        "$TARGET/main/apps/app_codex/ble/"
cp "$REPO_ROOT"/firmware/app_codex/ble/ble_nus.cpp      "$TARGET/main/apps/app_codex/ble/"
cp "$REPO_ROOT"/firmware/app_codex/net/net.h            "$TARGET/main/apps/app_codex/net/"
cp "$REPO_ROOT"/firmware/app_codex/net/net.cpp          "$TARGET/main/apps/app_codex/net/"
cp "$REPO_ROOT"/firmware/app_codex/net/net_config.h     "$TARGET/main/apps/app_codex/net/"
cp "$REPO_ROOT"/firmware/app_codex/debug/debug_screenshot.h   "$TARGET/main/apps/app_codex/debug/"
cp "$REPO_ROOT"/firmware/app_codex/debug/debug_screenshot.cpp "$TARGET/main/apps/app_codex/debug/"
cp "$REPO_ROOT"/firmware/assets/logo_claude.c           "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/assets/logo_codex.c            "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/assets/logo_opencode.c         "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/assets/icon_cc_island.c        "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/app_printsphere/app_printsphere.h \
   "$TARGET/main/apps/app_printsphere/"
cp "$REPO_ROOT"/firmware/app_printsphere/app_printsphere.cpp \
   "$TARGET/main/apps/app_printsphere/"
cp "$REPO_ROOT"/firmware/hub_wifi/hub_wifi.h \
   "$TARGET/main/services/hub_wifi/"
cp "$REPO_ROOT"/firmware/hub_wifi/hub_wifi.cpp \
   "$TARGET/main/services/hub_wifi/"
cp "$REPO_ROOT"/firmware/hub_wifi/hub_wifi_config.h \
   "$TARGET/main/services/hub_wifi/"
cp "$REPO_ROOT"/firmware/hub_time/hub_time.h \
   "$TARGET/main/services/hub_time/"
cp "$REPO_ROOT"/firmware/hub_time/hub_time.cpp \
   "$TARGET/main/services/hub_time/"
cp "$REPO_ROOT"/firmware/printsphere_m5/printsphere_runtime.h \
   "$TARGET/main/platform/printsphere_m5/"
cp "$REPO_ROOT"/firmware/printsphere_m5/printsphere_runtime.cpp \
   "$TARGET/main/platform/printsphere_m5/"
cp "$REPO_ROOT"/firmware/assets/icon_printsphere.c      "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/partitions.csv                 "$TARGET/partitions.csv"
python3 "$REPO_ROOT/scripts/prepare_printsphere_port.py" "$REPO_ROOT" "$TARGET"
# Remove files from the pre-hub launcher and the earlier PrintSphere scaffold
# when upgrading an existing generated checkout.
rm -f "$TARGET/main/assets/images/icon_codex.c" \
      "$TARGET/main/assets/images/icon_bambu_status.c" \
      "$TARGET/main/apps/app_bambu_status/app_bambu_status.h" \
      "$TARGET/main/apps/app_bambu_status/app_bambu_status.cpp" \
      "$TARGET/main/services/printsphere_core/include/printsphere/printer_state.hpp" \
      "$TARGET/main/services/printsphere_core/include/printsphere/bambu_status.hpp" \
      "$TARGET/main/services/printsphere_core/src/printer_state.cpp" \
      "$TARGET/main/services/printsphere_core/src/bambu_status.cpp"

# 3b. Bake WiFi + bridge settings from the gitignored .env (if present) into
#     the copied net_config.h. Without .env, the committed placeholders stay.
echo "==> Applying .env network settings (if present)..."
python3 - "$REPO_ROOT" "$TARGET" "$ENV_FILE" <<'PY'
import os, re, sys, pathlib
root, target, env_path = map(pathlib.Path, sys.argv[1:4])
env = {}
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

def cstr(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')

hub_cfg = root / "firmware/hub_wifi/hub_wifi_config.h"
hub_text = hub_cfg.read_text()
if "CC_WIFI_SSID" in env and env.get("CC_WIFI_SSID"):
    hub_text = re.sub(r'\.ssid\s*=\s*"[^"]*"',
                      f'.ssid = "{cstr(env["CC_WIFI_SSID"])}"', hub_text)
if "CC_WIFI_PASSWORD" in env and env.get("CC_WIFI_PASSWORD"):
    hub_text = re.sub(r'\.password\s*=\s*"[^"]*"',
                      f'.password = "{cstr(env["CC_WIFI_PASSWORD"])}"', hub_text)
(target / "main/services/hub_wifi/hub_wifi_config.h").write_text(hub_text)

cfg = root / "firmware/app_codex/net/net_config.h"
text = cfg.read_text()
if "CC_BRIDGE_HOST" in env and env.get("CC_BRIDGE_HOST"):
    text = re.sub(r'\.host\s*=\s*"[^"]*"',
                  f'.host    = "{cstr(env["CC_BRIDGE_HOST"])}"', text)
if "CC_BRIDGE_PORT" in env and env.get("CC_BRIDGE_PORT"):
    text = re.sub(r'\.port\s*=\s*\d+',
                  f'.port    = {env["CC_BRIDGE_PORT"]}', text)
if "CC_POLL_MS" in env and env.get("CC_POLL_MS"):
    text = re.sub(r'\.poll_ms\s*=\s*\d+',
                  f'.poll_ms = {env["CC_POLL_MS"]}', text)
(target / "main/apps/app_codex/net/net_config.h").write_text(text)

# app_codex_config.h: page layout, optional system monitor, auto-switch interval
cfg2 = root / "firmware/app_codex/app_codex_config.h"
text2 = cfg2.read_text()

def env_bool(name):
    value = env[name].strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name} must be true/false, got {env[name]!r}")

if "CC_LAYOUT" in env and env.get("CC_LAYOUT"):
    pages = env["CC_LAYOUT"].strip().lower() == "pages"
    text2 = re.sub(r'kLayoutPages\s*=\s*(true|false)',
                   f'kLayoutPages = {"true" if pages else "false"}', text2)
if "CC_SYSTEM_MONITOR" in env and env.get("CC_SYSTEM_MONITOR"):
    enabled = env_bool("CC_SYSTEM_MONITOR")
    text2 = re.sub(r'kShowSystemPage\s*=\s*(true|false)',
                   f'kShowSystemPage = {"true" if enabled else "false"}', text2)
if "CC_AUTO_SWITCH_MS" in env and env.get("CC_AUTO_SWITCH_MS") is not None:
    text2 = re.sub(r'kAutoSwitchMs\s*=\s*\d+',
                   f'kAutoSwitchMs = {env["CC_AUTO_SWITCH_MS"]}', text2)
(target / "main/apps/app_codex/app_codex_config.h").write_text(text2)
print("   shared Wi-Fi and app configs updated from .env" if "CC_WIFI_SSID" in env else
      "   no Wi-Fi .env config — keeping setup-required defaults")
PY

# 4. Apply the small, idempotent edits to the factory sources.
echo "==> Registering the app (idempotent edits)..."
python3 - "$TARGET" <<'PY'
import re, sys, pathlib
root = pathlib.Path(sys.argv[1])

def replace_once(text, old, new, label):
    if new and new in text:
        return text
    old_count = text.count(old)
    if old_count == 1:
        return text.replace(old, new, 1)
    raise SystemExit(f"{label}: expected source or patched anchor, found {old_count}")

def insert_after(path, anchor, line):
    p = root / path
    text = p.read_text()
    if line.strip() in text:
        return
    out, done = [], False
    for ln in text.splitlines():
        out.append(ln)
        if not done and anchor in ln:
            out.append(line)
            done = True
    if not done:
        raise SystemExit(f"anchor not found in {path}: {anchor!r}")
    p.write_text("\n".join(out) + "\n")
    print(f"   patched {path}")

def remove_line(path, line):
    p = root / path
    text = p.read_text()
    updated = "\n".join(item for item in text.splitlines() if item.strip() != line.strip()) + "\n"
    if updated != text:
        p.write_text(updated)
        print(f"   removed legacy entry from {path}")

# Upgrade generated checkouts from the earlier Bambu Status scaffold.
remove_line("main/apps/apps.h", '#include "app_bambu_status/app_bambu_status.h"')
remove_line("main/main.cpp",
            "    GetMooncake().installApp(std::make_unique<AppBambuStatus>());")

# apps.h: include the app header
insert_after("main/apps/apps.h",
             '#include "app_template/app_template.h"',
             '#include "app_codex/app_codex.h"')
insert_after("main/apps/apps.h",
             '#include "app_codex/app_codex.h"',
             '#include "app_printsphere/app_printsphere.h"')

# main.cpp: install the app
insert_after("main/main.cpp",
             "GetMooncake().installApp(std::make_unique<AppSetup>());",
             "    GetMooncake().installApp(std::make_unique<AppCodex>());")
insert_after("main/main.cpp",
             "GetMooncake().installApp(std::make_unique<AppCodex>());",
             "    GetMooncake().installApp(std::make_unique<AppPrintSphere>());")

# main CMakeLists: compile service/platform sources and expose core headers.
insert_after("main/CMakeLists.txt",
             '    "apps/*.cpp"',
             '    "services/*.c"\n'
             '    "services/*.cc"\n'
             '    "services/*.cpp"\n'
             '    "platform/*.c"\n'
             '    "platform/*.cc"\n'
             '    "platform/*.cpp"')
insert_after("main/CMakeLists.txt",
             '    "."',
             '    "services/printsphere/include"')

cmake = root / "main/CMakeLists.txt"
cmake_text = cmake.read_text().replace('    "services/printsphere_core/include"\n', "")
embed_anchor = '        "hal/utils/config_ap/assets/badge_config_ap.html"'
embed_lines = (
    '        "services/printsphere/include/certs/bambu.cert"\n'
    '        "services/printsphere/include/certs/bambu_p2s_250626.cert"\n'
    '        "services/printsphere/include/certs/bambu_h2c_251122.cert"\n'
    '        "services/printsphere/include/certs/bambu_x2c_260425.cert"\n'
    '        "services/printsphere/include/error_lookup/error_lookup.tsv"'
)
if embed_lines not in cmake_text:
    if embed_anchor not in cmake_text:
        raise SystemExit("EMBED_TXTFILES anchor not found in main/CMakeLists.txt")
    cmake_text = cmake_text.replace(embed_anchor, embed_anchor + "\n" + embed_lines, 1)

define_lines = (
    '\ntarget_compile_definitions(${COMPONENT_LIB} PRIVATE\n'
    '    PRINTSPHERE_RELEASE_VERSION="v1.6.2"\n'
    '    PRINTSPHERE_HW_VARIANT_AMOLED_1_75=1\n'
    ')\n'
)
if "PRINTSPHERE_RELEASE_VERSION" not in cmake_text:
    cmake_text = cmake_text.rstrip() + define_lines
cmake.write_text(cmake_text)

manifest = root / "main/idf_component.yml"
manifest_text = manifest.read_text()
dependencies = (
    "  espressif/cjson: ^1.7.19\n"
    "  espressif/mqtt: ^1.0.0\n"
    "  espressif/esp_new_jpeg: '*'\n"
    "  espressif/libpng: '*'\n"
)
if "espressif/esp_new_jpeg:" not in manifest_text:
    manifest.write_text(manifest_text.rstrip() + "\n" + dependencies)

# assets.h: declare the images
assets_h = root / "main/assets/assets.h"
assets_text = assets_h.read_text().replace(
    "LV_IMG_DECLARE(icon_codex);", "LV_IMG_DECLARE(icon_cc_island);")
assets_text = assets_text.replace("LV_IMG_DECLARE(icon_bambu_status);\n", "")
assets_h.write_text(assets_text)

insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_watch_face);",
             "LV_IMG_DECLARE(icon_cc_island);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_cc_island);",
             "LV_IMG_DECLARE(icon_printsphere);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_printsphere);",
             "LV_IMG_DECLARE(logo_claude);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(logo_claude);",
             "LV_IMG_DECLARE(logo_codex);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(logo_codex);",
             "LV_IMG_DECLARE(logo_opencode);")

# The built-in badge configuration portal temporarily owns global Wi-Fi in AP
# mode. Cooperate with hub_wifi and accept an already initialized driver.
insert_after("main/hal/utils/config_ap/config_ap.cpp",
             '#include "config_ap.h"',
             '#include <services/hub_wifi/hub_wifi.h>')

config_ap = root / "main/hal/utils/config_ap/config_ap.cpp"
config_text = config_ap.read_text()
wifi_init_old = (
    'if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE) {\n'
    '        ESP_LOGE(_tag, "wifi init failed: %s", esp_err_to_name(ret));'
)
wifi_init_new = (
    'if (ret != ESP_OK && ret != ESP_ERR_INVALID_STATE && '\
    'ret != ESP_ERR_WIFI_INIT_STATE) {\n'
    '        ESP_LOGE(_tag, "wifi init failed: %s", esp_err_to_name(ret));'
)
if wifi_init_old in config_text:
    config_text = config_text.replace(wifi_init_old, wifi_init_new, 1)
elif wifi_init_new not in config_text:
    raise SystemExit("Wi-Fi init guard anchor not found in config_ap.cpp")

ap_start_old = (
    '    bool start_access_point()\n'
    '    {\n'
    '        static esp_netif_t* ap_netif = nullptr;'
)
ap_start_new = (
    '    bool start_access_point()\n'
    '    {\n'
    '        hub_wifi::suspend_for_exclusive_use();\n'
    '        static esp_netif_t* ap_netif = nullptr;'
)
if ap_start_old in config_text:
    config_text = config_text.replace(ap_start_old, ap_start_new, 1)
elif ap_start_new not in config_text:
    raise SystemExit("AP start anchor not found in config_ap.cpp")

netif_old = (
    '        if (ap_netif == nullptr) {\n'
    '            ap_netif = esp_netif_create_default_wifi_ap();'
)
netif_lookup = (
    '        if (ap_netif == nullptr) {\n'
    '            ap_netif = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");\n'
    '        }\n'
)
while netif_lookup + netif_lookup in config_text:
    config_text = config_text.replace(netif_lookup + netif_lookup, netif_lookup, 1)
if netif_lookup not in config_text and netif_old in config_text:
    config_text = config_text.replace(netif_old, netif_lookup + netif_old, 1)
elif netif_lookup not in config_text:
    raise SystemExit("shared AP netif anchor not found in config_ap.cpp")

ap_stop_old = (
    '        if (ret != ESP_OK && ret != ESP_ERR_WIFI_NOT_STARTED && ret != ESP_ERR_WIFI_MODE) {\n'
    '            ESP_LOGW(_tag, "wifi stop failed: %s", esp_err_to_name(ret));\n'
    '        }\n\n'
    '        if (_event_group != nullptr) {'
)
ap_stop_new = (
    '        if (ret != ESP_OK && ret != ESP_ERR_WIFI_NOT_STARTED && ret != ESP_ERR_WIFI_MODE) {\n'
    '            ESP_LOGW(_tag, "wifi stop failed: %s", esp_err_to_name(ret));\n'
    '        }\n'
    '        hub_wifi::resume_after_exclusive_use();\n\n'
    '        if (_event_group != nullptr) {'
)
if ap_stop_old in config_text:
    config_text = config_text.replace(ap_stop_old, ap_stop_new, 1)
elif ap_stop_new not in config_text:
    raise SystemExit("AP stop anchor not found in config_ap.cpp")
config_ap.write_text(config_text)

# sdkconfig.defaults: enable NimBLE (BLE transport) + Wi-Fi (polling transport)
sdk = root / "sdkconfig.defaults"
txt = sdk.read_text()
if "CONFIG_BT_NIMBLE_ENABLED=y" not in txt:
    sdk.write_text(txt.rstrip() + "\n\n# BLE (NimBLE) for CC Island usage push\n"
                   "CONFIG_BT_ENABLED=y\nCONFIG_BT_NIMBLE_ENABLED=y\n")
    print("   patched sdkconfig.defaults (NimBLE)")
if "CONFIG_ESP_WIFI_ENABLED=y" not in sdk.read_text():
    sdk.write_text(sdk.read_text().rstrip() + "\n# Wi-Fi (CC Island polling transport)\n"
                   "CONFIG_ESP_WIFI_ENABLED=y\n")
    print("   patched sdkconfig.defaults (Wi-Fi)")
# The factory launcher and full PrintSphere UI share internal SRAM. Move
# MbedTLS allocations plus ESP-MQTT task stacks/buffers to PSRAM, prefer PSRAM
# for general allocations above 4 KiB, and reserve 192 KiB exclusively for
# Wi-Fi, NimBLE, AMOLED DMA, and RTOS-only capabilities during concurrent
# PrintSphere and CC Island activity. PrintSphere MQTT event handlers only parse/update runtime
# state and never perform NVS/FAT writes or sleep operations, which is required
# when those task stacks live in external memory.
# Patch both defaults and an existing generated sdkconfig: sdkconfig takes
# precedence over defaults, which was the reason the original upstream
# PrintSphere setting did not survive the factory-firmware integration.
def set_kconfig(text, key, value):
    desired = f"{key}={value}" if value is not None else f"# {key} is not set"
    output = []
    found = False
    for line in text.splitlines():
        if line.startswith(f"{key}=") or line == f"# {key} is not set":
            if not found:
                output.append(desired)
                found = True
        else:
            output.append(line)
    if not found:
        output.append(desired)
    return "\n".join(output).rstrip() + "\n"

memory_settings = (
    # Real-device high-water profiling after Wi-Fi, BLE, Web Config and six
    # launcher/App transitions used about 5.4 KiB of the main task and 2.8 KiB
    # of the system event task. Preserve at least ~1.7 KiB and ~2.3 KiB while
    # returning 4 KiB of permanently reserved internal SRAM.
    ("CONFIG_ESP_MAIN_TASK_STACK_SIZE", "7168"),
    ("CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE", "5120"),
    # The peripheral-only NimBLE host reached a 388-byte low-water mark with
    # the stock 4 KiB stack. Give it another KiB rather than risking a BLE
    # stack overflow while reclaiming memory elsewhere.
    ("CONFIG_BT_NIMBLE_HOST_TASK_STACK_SIZE", "5120"),
    ("CONFIG_SPIRAM_MALLOC_ALWAYSINTERNAL", "4096"),
    # NimBLE controller and AMOLED QSPI DMA buffers are internal-only. Keep a
    # 192 KiB capability pool so opening CC Island after the full PrintSphere
    # runtime does not exhaust BLE or display-flush allocations.
    ("CONFIG_SPIRAM_MALLOC_RESERVE_INTERNAL", "196608"),
    ("CONFIG_FREERTOS_TASK_CREATE_ALLOW_EXT_MEM", "y"),
    ("CONFIG_MQTT_TASK_STACK_ON_EXTERNAL_MEMORY", "y"),
    ("CONFIG_MQTT_BUFFERS_ON_EXTERNAL_MEMORY", "y"),
    # Preserve PrintSphere's upstream PSRAM/TLS policy in the generated factory
    # sdkconfig too. Without these explicit overrides, Wi-Fi/LwIP and hardware
    # AES consume the same internal DMA heap needed by the AMOLED panel.
    ("CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP", "y"),
    ("CONFIG_MBEDTLS_DYNAMIC_BUFFER", "y"),
    ("CONFIG_MBEDTLS_DYNAMIC_FREE_CONFIG_DATA", "y"),
    ("CONFIG_MBEDTLS_DYNAMIC_FREE_CA_CERT", "y"),
    ("CONFIG_MBEDTLS_SSL_KEEP_PEER_CERTIFICATE", None),
    ("CONFIG_MBEDTLS_HARDWARE_AES", None),
    ("CONFIG_MBEDTLS_HARDWARE_SHA", None),
    # CC Island is one unencrypted NUS peripheral. Keep controller/DMA state
    # internal, but put the supported NimBLE host pools in PSRAM and remove the
    # unused central, observer, client, security and extra-connection capacity.
    ("CONFIG_BT_NIMBLE_MEM_ALLOC_MODE_INTERNAL", None),
    ("CONFIG_BT_NIMBLE_MEM_ALLOC_MODE_EXTERNAL", "y"),
    ("CONFIG_BT_NIMBLE_MEM_ALLOC_MODE_DEFAULT", None),
    ("CONFIG_BT_NIMBLE_MEM_ALLOC_MODE_IRAM_8BIT", None),
    ("CONFIG_BT_NIMBLE_ROLE_CENTRAL", None),
    ("CONFIG_BT_NIMBLE_ROLE_PERIPHERAL", "y"),
    ("CONFIG_BT_NIMBLE_ROLE_BROADCASTER", "y"),
    ("CONFIG_BT_NIMBLE_ROLE_OBSERVER", None),
    ("CONFIG_BT_NIMBLE_GATT_CLIENT", None),
    ("CONFIG_BT_NIMBLE_GATT_SERVER", "y"),
    ("CONFIG_BT_NIMBLE_SECURITY_ENABLE", None),
    ("CONFIG_BT_NIMBLE_HS_PVCY", None),
    ("CONFIG_BT_NIMBLE_50_FEATURE_SUPPORT", None),
    ("CONFIG_BT_NIMBLE_DTM_MODE_TEST", None),
    ("CONFIG_BT_NIMBLE_MAX_CONNECTIONS", "1"),
    ("CONFIG_BT_NIMBLE_MAX_CCCDS", "2"),
    ("CONFIG_BT_CTRL_BLE_MAX_ACT", "2"),
    ("CONFIG_BT_CTRL_DTM_ENABLE", None),
    # Despite its historical name, ESP32-S3's controller Kconfig describes
    # this as the BLE connection feature. A NUS peripheral needs it enabled to
    # accept CONNECT_IND while the NimBLE Host central role remains disabled.
    ("CONFIG_BT_CTRL_BLE_MASTER", "y"),
    ("CONFIG_BT_CTRL_BLE_SCAN", None),
    ("CONFIG_BT_CTRL_BLE_SECURITY_ENABLE", None),
    ("CONFIG_BT_CTRL_BLE_ADV", "y"),
    ("CONFIG_BT_NIMBLE_ATT_MAX_PREP_ENTRIES", "4"),
    ("CONFIG_BT_NIMBLE_GATT_MAX_PROCS", "2"),
    ("CONFIG_BT_NIMBLE_MSYS_2_BLOCK_COUNT", "12"),
    ("CONFIG_BT_NIMBLE_TRANSPORT_ACL_FROM_LL_COUNT", "12"),
    ("CONFIG_BT_NIMBLE_TRANSPORT_EVT_COUNT", "12"),
    ("CONFIG_BT_NIMBLE_TRANSPORT_EVT_DISCARD_COUNT", "2"),
    ("CONFIG_LWIP_SNTP_MAX_SERVERS", "3"),
    ("CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC", None),
    ("CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC", "y"),
    ("CONFIG_MBEDTLS_DEFAULT_MEM_ALLOC", None),
    ("CONFIG_MBEDTLS_CUSTOM_MEM_ALLOC", None),
)
for sdk_path in (sdk, root / "sdkconfig"):
    if not sdk_path.exists():
        continue
    sdk_text = sdk_path.read_text()
    for key, value in memory_settings:
        sdk_text = set_kconfig(sdk_text, key, value)
    sdk_path.write_text(sdk_text)
    print(f"   patched {sdk_path.name} (TLS and shared PSRAM policy)")

# The factory RX8130 driver subtracts 100 directly from the caller-owned
# struct tm before writing the two-digit year. The RTC bytes are correct, but
# the mutation makes the HAL report 1926 immediately after persisting 2026 and
# can surprise any future caller that reuses the struct. Compute the two-digit
# year without modifying the input object.
rtc_driver = root / "main/hal/drivers/rx8130/rx8130.cpp"
rtc_text = rtc_driver.read_text()
mutating_year = "    time->tm_year -= 100;\n\n"
nonmutating_year = (
    "    // tm_year is years since 1900. RX8130 stores only the final two digits;\n"
    "    // do not mutate the caller-owned struct while converting it.\n"
)
if mutating_year in rtc_text:
    rtc_text = rtc_text.replace(mutating_year, nonmutating_year, 1)
elif nonmutating_year not in rtc_text:
    raise SystemExit("RX8130 year conversion anchor not found")
rtc_driver.write_text(rtc_text)
print("   patched RX8130 year conversion (non-mutating UTC persistence)")

# LVGL's CLIB backend normally follows the global small-allocation preference,
# so every widget/style from PrintSphere, Launcher and CC Island competes for
# scarce internal SRAM even though none of that object graph is DMA data. Keep
# LVGL's explicit display/DMA buffers untouched and move only its heap objects
# to PSRAM, with an internal fallback for degraded boots.
lvgl_mem = root / "components/lvgl/src/stdlib/clib/lv_mem_core_clib.c"
lvgl_text = lvgl_mem.read_text()
lvgl_include_old = "#include <stdlib.h>\n"
lvgl_include_new = "#include <stdlib.h>\n#include <esp_heap_caps.h>\n"
if lvgl_include_new not in lvgl_text:
    if lvgl_include_old not in lvgl_text:
        raise SystemExit("LVGL CLIB include anchor not found")
    lvgl_text = lvgl_text.replace(lvgl_include_old, lvgl_include_new, 1)
lvgl_alloc_old = '''void * lv_malloc_core(size_t size)
{
    return malloc(size);
}

void * lv_realloc_core(void * p, size_t new_size)
{
    return realloc(p, new_size);
}
'''
lvgl_alloc_new = '''void * lv_malloc_core(size_t size)
{
    return heap_caps_malloc_prefer(size, 2,
                                   MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT,
                                   MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
}

void * lv_realloc_core(void * p, size_t new_size)
{
    return heap_caps_realloc_prefer(p, new_size, 2,
                                    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT,
                                    MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
}
'''
if lvgl_alloc_old in lvgl_text:
    lvgl_text = lvgl_text.replace(lvgl_alloc_old, lvgl_alloc_new, 1)
elif lvgl_alloc_new not in lvgl_text:
    raise SystemExit("LVGL CLIB allocator anchor not found")
lvgl_mem.write_text(lvgl_text)
print("   patched LVGL object allocator (PSRAM preferred, internal fallback)")

# M5GFX's AMOLED framebuffer flush allocates two sub-1-KiB DMA line buffers.
# Upstream FlipBuffer frees a reusable buffer whenever the requested width
# shrinks, then assumes the replacement allocation succeeds. Under concurrent
# Wi-Fi/BLE/TLS pressure that can return nullptr and crash in memcpy(). Retain
# the largest line buffers for the device lifetime, allocate replacements
# before releasing old storage, and let the panel skip/retry a frame if DMA is
# momentarily unavailable. Request a full framebuffer line from the first
# flush so both buffers reach their final size during early boot; otherwise
# progressively wider dirty rectangles cause repeated allocate-before-free
# peaks during later App transitions.
m5gfx_common = root / "components/M5GFX/src/lgfx/v1/platforms/common.hpp"
m5gfx_common_text = m5gfx_common.read_text()
flip_old = '''      if (_length[_flip] < length || _length[_flip] > length + 64)
      {
        if (_buffer[_flip]) { heap_free(_buffer[_flip]); }
        _buffer[_flip] = (uint8_t*)heap_alloc_dma(length);
        _length[_flip] = _buffer[_flip] ? length : 0;
      }
      return _buffer[_flip];
'''
flip_new = '''      if (_length[_flip] < length)
      {
        auto replacement = (uint8_t*)heap_alloc_dma(length);
        if (replacement)
        {
          if (_buffer[_flip]) { heap_free(_buffer[_flip]); }
          _buffer[_flip] = replacement;
          _length[_flip] = length;
        }
        else if (_buffer[_flip] == nullptr || _length[_flip] < length)
        {
          return nullptr;
        }
      }
      return _buffer[_flip];
'''
if flip_old in m5gfx_common_text:
    m5gfx_common_text = m5gfx_common_text.replace(flip_old, flip_new, 1)
elif flip_new not in m5gfx_common_text:
    raise SystemExit("M5GFX FlipBuffer allocation anchor not found")
m5gfx_common.write_text(m5gfx_common_text)

m5gfx_amoled = root / "components/M5GFX/src/lgfx/v1/panel/Panel_AMOLED.cpp"
m5gfx_amoled_text = m5gfx_amoled.read_text()
amoled_old = '''            buf[0] = bus->getDMABuffer(wb);
            buf[1] = bus->getDMABuffer(wb);

            _panel->start_qspi();
'''
amoled_new = '''            // Allocate both reusable DMA buffers at their final full-line
            // capacity during the first flush, while boot heap is still abundant.
            // The active dirty rectangle still controls memcpy/write length below.
            const size_t dma_wb = stride;
            buf[0] = bus->getDMABuffer(dma_wb);
            buf[1] = bus->getDMABuffer(dma_wb);
            if (buf[0] == nullptr || buf[1] == nullptr)
            {
                return;
            }

            _panel->start_qspi();
'''
if amoled_old in m5gfx_amoled_text:
    m5gfx_amoled_text = m5gfx_amoled_text.replace(amoled_old, amoled_new, 1)
elif not ("const size_t dma_wb = stride;" in m5gfx_amoled_text and
          "if (buf[0] == nullptr || buf[1] == nullptr)" in m5gfx_amoled_text):
    raise SystemExit("M5GFX AMOLED DMA guard anchor not found")
m5gfx_amoled.write_text(m5gfx_amoled_text)
print("   patched M5GFX AMOLED DMA buffers (pre-sized and allocation-safe)")

# The stock launcher creates five complete icon carousels on every App close.
# With PrintSphere and CC Island installed that briefly duplicates enough C++
# wrapper/signal state to exhaust internal SRAM, even though the final view
# fits. Three copies still provide the same seamless infinite carousel (left
# backup, center, right backup). Reserve all temporary vectors and move the
# label list so construction does not repeatedly allocate/copy while MQTT and
# Web Config are alive.
launcher_view = root / "main/apps/app_launcher/view/view.cpp"
launcher_text = launcher_view.read_text()
# Repair checkouts produced by the pre-idempotence installer, which could add
# another utility include on every rerun because the old anchor was a prefix of
# the replacement.
launcher_text = re.sub(r"(?:#include <utility>\n)+", "#include <utility>\n", launcher_text)
launcher_text = replace_once(
    launcher_text,
    "#include <vector>\n",
    "#include <vector>\n#include <utility>\n",
    "launcher utility include",
)
launcher_text = replace_once(
    launcher_text,
    "        _page_gap = pageGap;\n\n        _panel = std::make_unique<Container>(parent);",
    "        _page_gap = pageGap;\n        _dots.reserve(pageNum);\n\n"
    "        _panel = std::make_unique<Container>(parent);",
    "launcher page-dot reserve",
)
launcher_text = replace_once(
    launcher_text,
    "    void init(const std::vector<std::string>& iconLabelTexts, int iconGap, lv_obj_t* parent)\n"
    "    {\n"
    "        _icon_label_texts = iconLabelTexts;",
    "    void init(std::vector<std::string> iconLabelTexts, int iconGap, lv_obj_t* parent)\n"
    "    {\n"
    "        _icon_label_texts = std::move(iconLabelTexts);",
    "launcher label vector move",
)
launcher_text = replace_once(
    launcher_text,
    "// Create 5 copies: [0:Backup] [1:Buffer] [2:Main] [3:Buffer] [4:Backup]\n"
    "static constexpr int _loop_copies       = 5;\n"
    "static constexpr int _center_copy_index = 2;",
    "// Three copies are sufficient for a seamless infinite carousel:\n"
    "// [0:Backup] [1:Main] [2:Backup].\n"
    "static constexpr int _loop_copies       = 3;\n"
    "static constexpr int _center_copy_index = 1;",
    "launcher carousel copy count",
)
launcher_text = replace_once(
    launcher_text,
    "    std::vector<std::string> icon_label_texts;\n"
    "    std::vector<uint32_t> step_colors;",
    "    std::vector<std::string> icon_label_texts;\n"
    "    const size_t repeated_icon_count = appPorps.size() * _loop_copies;\n"
    "    _icon_panels.reserve(repeated_icon_count);\n"
    "    _icon_images.reserve(repeated_icon_count);\n"
    "    icon_label_texts.reserve(repeated_icon_count);\n"
    "    _lr_indicator_panels.reserve(2);\n"
    "    _lr_indicators_images.reserve(2);",
    "launcher vector reserves",
)
unused_step_colors = '''            uint32_t color = 0xDADADA;
            if (props.info.userData != nullptr) {
                color = *(uint32_t*)props.info.userData;
            }
            step_colors.push_back(color);

'''
if unused_step_colors in launcher_text:
    launcher_text = launcher_text.replace(unused_step_colors, "", 1)
elif "step_colors" in launcher_text:
    raise SystemExit("launcher unused step colors anchor not found")
launcher_text = replace_once(
    launcher_text,
    "    _dynamic_icon_label->init(icon_label_texts, _icon_gap, _panel->get());",
    "    _dynamic_icon_label->init(std::move(icon_label_texts), _icon_gap, _panel->get());",
    "launcher label move call",
)
launcher_text = replace_once(
    launcher_text,
    "    // Copy Index: 0 1 [2] 3 4",
    "    // Copy Index: 0 [1] 2",
    "launcher wrap comment",
)
launcher_text = replace_once(
    launcher_text,
    "    int left_trigger_limit  = 1 * set_width_px + (set_width_px / 2);  // Middle of Set 1\n"
    "    int right_trigger_limit = 3 * set_width_px + (set_width_px / 2);  // Middle of Set 3",
    "    int left_trigger_limit  = set_width_px / 2;                       // Middle of Set 0\n"
    "    int right_trigger_limit = 2 * set_width_px + (set_width_px / 2); // Middle of Set 2",
    "launcher three-copy wrap thresholds",
)
launcher_view.write_text(launcher_text)
print("   patched Launcher carousel (three copies and reserved vectors)")

# The stock LVGL worker reserves 16 KiB of internal stack. Real-device
# high-water profiling across the full Launcher, PrintSphere, CC Island and
# Repeated PrintSphere/Launcher cycling later reached about 9.5 KiB, including
# nested snapshot/UI work. Keep a 12 KiB flash-safe stack (about 2.5 KiB
# measured headroom) while leaving enough internal heap for Launcher peaks.
hal_display = root / "main/hal/hal_display.cpp"
hal_display_text = hal_display.read_text()
hal_display_text = replace_once(
    hal_display_text,
    '    xTaskCreate(lvgl_rtos_task, "lvgl_rtos_task", 4096 * 4, NULL, 1, NULL);',
    '    // Profiled peak was ~9.5 KiB; 12 KiB preserves ~2.5 KiB headroom.\n'
    '    xTaskCreate(lvgl_rtos_task, "lvgl_rtos_task", 12288, NULL, 1, NULL);',
    "LVGL worker stack",
)
hal_display.write_text(hal_display_text)
print("   patched LVGL worker stack (12 KiB, profile-backed)")
PY

cat <<EOF

==> Done. Next steps:

  1. Install ESP-IDF v5.5.4 and source it:
       . ~/esp/esp-idf/export.sh
  2. Build + flash (device in your USB port):
       cd "$TARGET"
       idf.py build
       idf.py -p /dev/cu.usbmodemXXXX flash

  (If you added/changed files later, run: idf.py reconfigure)
EOF
