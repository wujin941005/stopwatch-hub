#!/usr/bin/env python3
"""Capture a screenshot from the M5Stack StopWatch over USB Serial JTAG.

Sends 'P' to the firmware's debug screenshot handler (firmware/app_codex/debug),
reads the base64 RGB565 rows it replies with, and writes a PNG.

Usage: python3 tools/screenshot.py [output.png] [--port /dev/ttyACM0]
       [--advance PAGES]
"""
import argparse
import base64
import re
import sys
import time

import serial
from PIL import Image


def capture(port: str, timeout_s: float = 20.0, advance: int = 0):
    s = serial.Serial(port, 115200, timeout=0.2)
    s.reset_input_buffer()
    if advance:
        command = b"N" if advance > 0 else b"B"
        for _ in range(abs(advance)):
            s.write(command)
            s.flush()
            time.sleep(0.25)
    s.write(b"P")
    s.flush()

    w = h = None
    rows = []
    deadline = time.time() + timeout_s
    buf = b""
    state = "scan"
    while time.time() < deadline:
        chunk = s.read(65536)
        if chunk:
            buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if state == "scan":
                if line.startswith(b"@@SS:BEGIN:"):
                    m = re.search(rb"@@SS:BEGIN:(\d+):(\d+)@@", line)
                    if m:
                        w, h = int(m.group(1)), int(m.group(2))
                        state = "rows"
                        print(f"screenshot {w}x{h}")
            elif state == "rows":
                if line.startswith(b"@@SS:END@@"):
                    state = "done"
                    break
                # Skip firmware log lines that got interleaved into the stream.
                if len(line) >= 4 and (len(line) % 4 == 0):
                    try:
                        raw = base64.b64decode(line, validate=True)
                        if w and len(raw) == w * 2:
                            rows.append(raw)
                    except Exception:
                        pass
        if state == "done":
            break
    s.close()

    if state != "done" or not w or not h or len(rows) != h:
        raise RuntimeError(f"capture failed (state={state}, rows={len(rows)})")

    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        raw = rows[y]
        for x in range(w):
            lo, hi = raw[2 * x], raw[2 * x + 1]
            v = lo | (hi << 8)
            r = ((v >> 11) & 0x1F) << 3
            g = ((v >> 5) & 0x3F) << 2
            b = (v & 0x1F) << 3
            px[x, y] = (r, g, b)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="cc_screenshot.png")
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument(
        "--advance", type=int, default=0, metavar="PAGES",
        help="switch pages before capture (positive=next, negative=previous)",
    )
    args = ap.parse_args()
    img = capture(args.port, advance=args.advance)
    img.save(args.out)
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
