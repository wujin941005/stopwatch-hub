#!/usr/bin/env bash
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
python3 - "$REPO_ROOT" "$TARGET" <<'PY'
import os, re, sys, pathlib
root, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
env = {}
env_path = root / ".env"
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
import sys, pathlib
root = pathlib.Path(sys.argv[1])

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
if "CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE=8192" not in sdk.read_text():
    sdk.write_text(sdk.read_text().rstrip() + "\n# Wi-Fi + NimBLE coexist needs a bigger event task\n"
                   "CONFIG_ESP_SYSTEM_EVENT_TASK_STACK_SIZE=8192\n")
    print("   patched sdkconfig.defaults (event task stack)")
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
