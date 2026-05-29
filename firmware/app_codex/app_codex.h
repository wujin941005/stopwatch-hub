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
 * @brief CodexIsland — shows Claude Code + Codex usage on one page.
 *
 * Phase 3: static placeholder values + two-row layout. Phase 4 will feed it
 * live numbers over BLE.
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
