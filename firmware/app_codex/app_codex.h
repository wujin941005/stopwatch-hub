/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <apps/common/key_manager/key_manager.h>
#include <mooncake.h>
#include <memory>

/**
 * @brief CC Island — AI usage and host monitoring for M5Stack StopWatch.
 *
 * Supports a compact two-provider page or separate Codex/OpenCode pages,
 * plus an optional host-system page. Data arrives over BLE or Wi-Fi polling;
 * pages can auto-rotate or be switched with horizontal swipes.
 */
class AppCodex : public mooncake::AppAbility {
public:
    AppCodex();

    void onCreate() override;
    void onOpen() override;
    void onRunning() override;
    void onClose() override;

private:
    std::unique_ptr<input::KeyManager> _key_manager;
};
