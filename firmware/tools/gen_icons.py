#!/usr/bin/env python3
"""Render brand SVGs to LVGL v9 RGB565 C arrays for app_codex.

Pipeline: SVG --(svglib/reportlab, scaled via dpi)--> black-on-white raster
--> coverage mask --> tint with brand color on black --> RGB565 LE --> .c file
matching the format of main/assets/images/icon_stopwatch.c.
"""
import io
import os

from svglib.svglib import svg2rlg
from reportlab.graphics import renderPM
from PIL import Image

SRC = os.path.dirname(os.path.abspath(__file__))
# Output dir for the generated LVGL .c files. Defaults to the repo's
# firmware/assets/ (committed copies); override with CC_ISLAND_ASSETS to write
# straight into a factory-firmware checkout's main/assets/images/.
OUT = os.environ.get(
    "CC_ISLAND_ASSETS", os.path.normpath(os.path.join(SRC, "..", "assets"))
)

CLAUDE = 0xF2854D
CODEX = 0x3B9EFF


def render_coverage(svg_name, size):
    """Return an 'L' image (0..255 coverage) of the monochrome SVG at size px."""
    d = svg2rlg(os.path.join(SRC, svg_name))
    dpi = 72.0 * size / float(d.width)
    pil = renderPM.drawToPIL(d, dpi=dpi, bg=0xFFFFFF).convert("L")
    if pil.size != (size, size):
        pil = pil.resize((size, size), Image.LANCZOS)
    # black shape on white bg -> invert so shape = high coverage
    return Image.eval(pil, lambda p: 255 - p)


def tint(cov, color):
    """Tint a coverage mask with `color` over a black background -> RGB image."""
    r, g, b = (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    out = Image.new("RGB", cov.size, (0, 0, 0))
    px, cv = out.load(), cov.load()
    for y in range(cov.height):
        for x in range(cov.width):
            a = cv[x, y] / 255.0
            px[x, y] = (int(r * a), int(g * a), int(b * a))
    return out


def paste_on(canvas, rgb, x, y):
    canvas.paste(rgb, (x, y))


def to_c(name, img):
    """Emit `<name>.c` with an RGB565-LE map + lv_image_dsc_t matching v9 format."""
    w, h = img.size
    px = img.load()
    data = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            data += bytes((v & 0xFF, (v >> 8) & 0xFF))  # little-endian
    up = name.upper()
    lines = [
        "#ifdef __has_include",
        '#if __has_include("lvgl.h")',
        "#ifndef LV_LVGL_H_INCLUDE_SIMPLE",
        "#define LV_LVGL_H_INCLUDE_SIMPLE",
        "#endif", "#endif", "#endif", "",
        "#if defined(LV_LVGL_H_INCLUDE_SIMPLE)",
        '#include "lvgl.h"', "#else", '#include "lvgl/lvgl.h"', "#endif", "",
        "#ifndef LV_ATTRIBUTE_MEM_ALIGN", "#define LV_ATTRIBUTE_MEM_ALIGN", "#endif", "",
        f"#ifndef LV_ATTRIBUTE_IMAGE_{up}", f"#define LV_ATTRIBUTE_IMAGE_{up}", "#endif", "",
        f"const LV_ATTRIBUTE_MEM_ALIGN LV_ATTRIBUTE_LARGE_CONST "
        f"LV_ATTRIBUTE_IMAGE_{up} uint8_t {name}_map[] = {{",
    ]
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        lines.append("    " + ", ".join(f"0x{b:02x}" for b in chunk) + ",")
    lines += [
        "};", "",
        f"const lv_image_dsc_t {name} = {{",
        "    .header.cf    = LV_COLOR_FORMAT_RGB565,",
        "    .header.magic = LV_IMAGE_HEADER_MAGIC,",
        f"    .header.w     = {w},",
        f"    .header.h     = {h},",
        f"    .data_size    = {w * h} * 2,",
        f"    .data         = {name}_map,",
        "};", "",
    ]
    with open(os.path.join(OUT, f"{name}.c"), "w") as f:
        f.write("\n".join(lines))
    print(f"  {name}.c  {w}x{h}  ({len(data)} bytes)")


def main():
    os.makedirs(OUT, exist_ok=True)
    print("Generating row logos (48x48):")
    to_c("logo_claude", tint(render_coverage("claude.svg", 48), CLAUDE))
    to_c("logo_codex", tint(render_coverage("openai.svg", 48), CODEX))

    print("Generating launcher icon (200x200):")
    launcher = Image.new("RGB", (200, 200), (0, 0, 0))
    paste_on(launcher, tint(render_coverage("claude.svg", 80), CLAUDE), 60, 10)
    paste_on(launcher, tint(render_coverage("openai.svg", 80), CODEX), 60, 110)
    to_c("icon_codex", launcher)


if __name__ == "__main__":
    main()
