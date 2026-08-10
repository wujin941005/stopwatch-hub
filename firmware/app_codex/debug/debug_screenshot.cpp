/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 *
 * Debug screenshot: dump the AMOLED panel framebuffer over the USB Serial JTAG
 * as base64 RGB565 rows so the host can reconstruct real screenshots (see
 * tools/screenshot.py). Host sends 'P', firmware answers:
 *   @@SS:BEGIN:<w>:<h>@@
 *   <base64 of one row> x h lines
 *   @@SS:END@@
 */
#include "debug_screenshot.h"

#include <atomic>
#include <hal/hal.h>
#include <cstdio>
#include <cstring>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <driver/usb_serial_jtag.h>

namespace {

constexpr const char* B64 =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

// Static buffers (no heap allocation) so the dump can't fail on low memory.
constexpr int kMaxW = 480;
static uint16_t s_row[kMaxW];
static char s_b64[kMaxW * 4 + 4];
static std::atomic<int> s_page_delta{0};

int b64_encode(const uint8_t* in, int inlen, char* out)
{
    int o = 0;
    for (int i = 0; i < inlen; i += 3) {
        uint32_t n = (uint32_t)in[i] << 16;
        if (i + 1 < inlen) n |= (uint32_t)in[i + 1] << 8;
        if (i + 2 < inlen) n |= (uint32_t)in[i + 2];
        out[o++] = B64[(n >> 18) & 63];
        out[o++] = B64[(n >> 12) & 63];
        out[o++] = (i + 1 < inlen) ? B64[(n >> 6) & 63] : '=';
        out[o++] = (i + 2 < inlen) ? B64[n & 63] : '=';
    }
    return o;
}

void dump()
{
    auto& display = GetHAL().getDisplay();
    const int w = display.width();
    const int h = display.height();
    if (w > kMaxW || w <= 0) return;

    auto send = [](const char* s, int n) {
        // The USB Serial/JTAG TX ring is 512 bytes, while one encoded display
        // row is about 1.25 KiB. Larger single writes are rejected, so stream
        // each row in bounded chunks.
        while (n > 0) {
            int chunk = n > 256 ? 256 : n;
            int sent = usb_serial_jtag_write_bytes(
                reinterpret_cast<const uint8_t*>(s), chunk, portMAX_DELAY);
            if (sent <= 0) break;
            s += sent;
            n -= sent;
        }
    };

    char header[64];
    int n = std::snprintf(header, sizeof(header), "@@SS:BEGIN:%d:%d@@\n", w, h);
    send(header, n);

    GetHAL().lvglLock();
    for (int y = 0; y < h; y++) {
        display.readRect(0, y, w, 1, s_row);
        int olen = b64_encode((const uint8_t*)s_row, w * 2, s_b64);
        s_b64[olen++] = '\n';
        send(s_b64, olen);
    }
    GetHAL().lvglUnlock();

    const char* end = "@@SS:END@@\n";
    send(end, (int)std::strlen(end));
}

void task(void*)
{
    for (;;) {
        char c = 0;
        int got = usb_serial_jtag_read_bytes((uint8_t*)&c, 1, pdMS_TO_TICKS(100));
        if (got == 1) {
            if (c == 'P') dump();
            else if (c == 'N') s_page_delta.fetch_add(1);
            else if (c == 'B') s_page_delta.fetch_sub(1);
        }
    }
}

}  // namespace

namespace debug_shot {

void start()
{
    static bool started = false;
    if (started) return;
    started = true;

    // The USJ driver must be installed before read/write bytes work.
    usb_serial_jtag_driver_config_t cfg = {
        .tx_buffer_size = 512,
        .rx_buffer_size = 512,
    };
    usb_serial_jtag_driver_install(&cfg);  // ignore "already installed"

    xTaskCreate(task, "cc_shot", 4096, nullptr, 3, nullptr);
}

int take_page_delta()
{
    return s_page_delta.exchange(0);
}

}  // namespace debug_shot
