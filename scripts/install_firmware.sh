#!/usr/bin/env bash
#
# Integrate the CC Island app into a fresh M5Stack StopWatch factory-firmware
# checkout, then you can build + flash with ESP-IDF.
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

echo "==> CC Island firmware integration"
echo "    repo:   $REPO_ROOT"
echo "    target: $TARGET"

# 1. Clone the factory firmware (MIT, by M5Stack) if not already present.
if [ ! -d "$TARGET/.git" ]; then
  echo "==> Cloning factory firmware..."
  git clone "$FACTORY_GIT" "$TARGET"
fi

# 2. Fetch the firmware's component dependencies (M5GFX, lvgl, mooncake, ...).
echo "==> Fetching firmware dependencies..."
( cd "$TARGET" && python3 ./fetch_repos.py )

# 3. Drop in the CC Island app + generated brand-logo bitmaps.
echo "==> Copying app_codex + assets..."
mkdir -p "$TARGET/main/apps/app_codex/ble" "$TARGET/main/assets/images"
cp "$REPO_ROOT"/firmware/app_codex/app_codex.h          "$TARGET/main/apps/app_codex/"
cp "$REPO_ROOT"/firmware/app_codex/app_codex.cpp        "$TARGET/main/apps/app_codex/"
cp "$REPO_ROOT"/firmware/app_codex/ble/ble_nus.h        "$TARGET/main/apps/app_codex/ble/"
cp "$REPO_ROOT"/firmware/app_codex/ble/ble_nus.cpp      "$TARGET/main/apps/app_codex/ble/"
cp "$REPO_ROOT"/firmware/assets/logo_claude.c           "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/assets/logo_codex.c            "$TARGET/main/assets/images/"
cp "$REPO_ROOT"/firmware/assets/icon_codex.c            "$TARGET/main/assets/images/"

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

# main.cpp: install the app
insert_after("main/main.cpp",
             "GetMooncake().installApp(std::make_unique<AppSetup>());",
             "    GetMooncake().installApp(std::make_unique<AppCodex>());")

# assets.h: declare the three images
insert_after("main/assets/assets.h",
             "LV_IMG_DECLARE(icon_watch_face);",
             "LV_IMG_DECLARE(icon_codex);\n"
             "LV_IMG_DECLARE(logo_claude);\n"
             "LV_IMG_DECLARE(logo_codex);")

# sdkconfig.defaults: enable NimBLE
sdk = root / "sdkconfig.defaults"
txt = sdk.read_text()
if "CONFIG_BT_NIMBLE_ENABLED=y" not in txt:
    sdk.write_text(txt.rstrip() + "\n\n# BLE (NimBLE) for CC Island usage push\n"
                   "CONFIG_BT_ENABLED=y\nCONFIG_BT_NIMBLE_ENABLED=y\n")
    print("   patched sdkconfig.defaults")
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
