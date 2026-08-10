/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once

// --------------------------------------------------------------------------- //
// CC Island app configuration — edit before flashing (or via .env /
// scripts/install_firmware.sh for CC_LAYOUT).
// --------------------------------------------------------------------------- //

// Page layout:
//   true  = one page per provider (Codex page / OpenCode page / system page),
//           each showing its own 5h + weekly(+monthly) windows with resets.
//   false = classic: one AI page with two providers side by side, plus a
//           system page. (Set from .env `CC_LAYOUT=pages|rows`.)
inline const bool kLayoutPages = false;

// Classic layout only — which two providers sit on the AI page:
//   "c"  Claude Code, "x"  Codex, "o"  OpenCode
inline const char* kTopProvider    = "o";   // top row
inline const char* kBottomProvider = "x";   // bottom row

// Auto-cycle pages every N ms. 0 disables auto-switching (swipe only).
// The orange button toggles auto/manual at runtime.
inline const uint32_t kAutoSwitchMs = 5000;

// Whether the system page (CPU / memory / disk / network of the host PC)
// participates in the page rotation. Set from .env `CC_SYSTEM_MONITOR` by
// scripts/install_firmware.sh; false preserves the original AI-only behavior.
inline const bool kShowSystemPage = false;
