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

echo "==> StopWatch Hub firmware integration"
echo "    repo:   $REPO_ROOT"
echo "    target: $TARGET"

# 1. Clone the factory firmware (MIT, by M5Stack) if not already present.
if [ ! -d "$TARGET/.git" ]; then
  echo "==> Cloning factory firmware..."
  git clone "$FACTORY_GIT" "$TARGET"
fi

# 2. Fetch the firmware's component dependencies (M5GFX, lvgl, mooncake, ...).
#    The opt-out is useful for a copied, already-populated offline build tree.
if [ "${STOPWATCH_HUB_SKIP_FETCH:-0}" = "1" ]; then
  echo "==> Skipping firmware dependency fetch (STOPWATCH_HUB_SKIP_FETCH=1)"
else
  echo "==> Fetching firmware dependencies..."
  ( cd "$TARGET" && python3 ./fetch_repos.py )
fi

# 3. Drop in both apps, the PrintSphere core/platform boundary, and assets.
echo "==> Copying StopWatch Hub apps, services, platform adapters, and assets..."
mkdir -p "$TARGET/main/apps/app_codex/ble" \
         "$TARGET/main/apps/app_codex/net" \
         "$TARGET/main/apps/app_codex/debug" \
         "$TARGET/main/apps/app_bambu_status" \
         "$TARGET/main/services/printsphere_core/include/printsphere" \
         "$TARGET/main/services/printsphere_core/src" \
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
cp "$REPO_ROOT"/firmware/app_bambu_status/app_bambu_status.h \
   "$TARGET/main/apps/app_bambu_status/"
cp "$REPO_ROOT"/firmware/app_bambu_status/app_bambu_status.cpp \
   "$TARGET/main/apps/app_bambu_status/"
cp "$REPO_ROOT"/firmware/printsphere_core/include/printsphere/printer_state.hpp \
   "$TARGET/main/services/printsphere_core/include/printsphere/"
cp "$REPO_ROOT"/firmware/printsphere_core/include/printsphere/bambu_status.hpp \
   "$TARGET/main/services/printsphere_core/include/printsphere/"
cp "$REPO_ROOT"/firmware/printsphere_core/src/printer_state.cpp \
   "$TARGET/main/services/printsphere_core/src/"
cp "$REPO_ROOT"/firmware/printsphere_core/src/bambu_status.cpp \
   "$TARGET/main/services/printsphere_core/src/"
cp "$REPO_ROOT"/firmware/printsphere_m5/printsphere_runtime.h \
   "$TARGET/main/platform/printsphere_m5/"
cp "$REPO_ROOT"/firmware/printsphere_m5/printsphere_runtime.cpp \
   "$TARGET/main/platform/printsphere_m5/"
cp "$REPO_ROOT"/firmware/assets/icon_bambu_status.c     "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/partitions.csv                 "$TARGET/partitions.csv"
# Remove the pre-CC-Island launcher asset when upgrading an existing checkout.
rm -f "$TARGET/main/assets/images/icon_codex.c"

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

cfg = root / "firmware/app_codex/net/net_config.h"
text = cfg.read_text()
if "CC_WIFI_SSID" in env and env.get("CC_WIFI_SSID"):
    text = re.sub(r'\.ssid\s*=\s*"[^"]*"',
                  f'.ssid    = "{cstr(env["CC_WIFI_SSID"])}"', text)
if "CC_WIFI_PASSWORD" in env and env.get("CC_WIFI_PASSWORD"):
    text = re.sub(r'\.password\s*=\s*"[^"]*"',
                  f'.password = "{cstr(env["CC_WIFI_PASSWORD"])}"', text)
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
print("   net_config.h updated from .env" if "CC_WIFI_SSID" in env else
      "   no .env — keeping placeholder net_config.h")
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

# apps.h: include the app header
insert_after("main/apps/apps.h",
             '#include "app_template/app_template.h"',
             '#include "app_codex/app_codex.h"')
insert_after("main/apps/apps.h",
             '#include "app_codex/app_codex.h"',
             '#include "app_bambu_status/app_bambu_status.h"')

# main.cpp: install the app
insert_after("main/main.cpp",
             "GetMooncake().installApp(std::make_unique<AppSetup>());",
             "    GetMooncake().installApp(std::make_unique<AppCodex>());")
insert_after("main/main.cpp",
             "GetMooncake().installApp(std::make_unique<AppCodex>());",
             "    GetMooncake().installApp(std::make_unique<AppBambuStatus>());")

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
             '    "services/printsphere_core/include"')

# assets.h: declare the images
assets_h = root / "main/assets/assets.h"
assets_text = assets_h.read_text().replace(
    "LV_IMG_DECLARE(icon_codex);", "LV_IMG_DECLARE(icon_cc_island);")
assets_h.write_text(assets_text)

insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_watch_face);",
             "LV_IMG_DECLARE(icon_cc_island);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_cc_island);",
             "LV_IMG_DECLARE(icon_bambu_status);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_bambu_status);",
             "LV_IMG_DECLARE(logo_claude);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(logo_claude);",
             "LV_IMG_DECLARE(logo_codex);")
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(logo_codex);",
             "LV_IMG_DECLARE(logo_opencode);")

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
