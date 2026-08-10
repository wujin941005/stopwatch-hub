/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

namespace debug_shot {

// Start a task that watches USB Serial JTAG. 'P' dumps the AMOLED framebuffer;
// 'N'/'B' queue a next/previous-page request (see tools/screenshot.py).
// Idempotent.
void start();

// Return and clear the page delta queued by the serial debug task.
int take_page_delta();

}  // namespace debug_shot
