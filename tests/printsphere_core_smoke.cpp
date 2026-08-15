/*
 * SPDX-FileCopyrightText: 2026 wangjiacheng
 *
 * SPDX-License-Identifier: MIT
 */
#include "printsphere/bambu_status.hpp"
#include "printsphere/printer_state.hpp"

#include <cassert>
#include <string>

int main()
{
    using namespace printsphere;

    assert(normalize_bambu_status_token("  print-ing ") == "PRINTING");
    assert(bambu_model_from_product_name("Bambu Lab A1 mini") == PrinterModel::kA1Mini);
    assert(bambu_model_from_product_name("X1 Carbon") == PrinterModel::kX1C);
    assert(lifecycle_from_bambu_status("RUNNING") == PrintLifecycleState::kPrinting);
    assert(lifecycle_from_bambu_status("PAUSE") == PrintLifecycleState::kPaused);
    assert(lifecycle_from_bambu_status("FAILED") == PrintLifecycleState::kError);
    assert(bambu_stage_label_from_id(13) == "homing_toolhead");

    PrinterStateStore store;
    PrinterSnapshot expected;
    expected.connection = PrinterConnectionState::kOnline;
    expected.lifecycle = PrintLifecycleState::kPrinting;
    expected.job_name = "core-smoke-test";
    expected.progress_percent = 42.5f;
    store.set_snapshot(expected);

    const PrinterSnapshot actual = store.snapshot();
    assert(actual.connection == PrinterConnectionState::kOnline);
    assert(actual.lifecycle == PrintLifecycleState::kPrinting);
    assert(actual.job_name == "core-smoke-test");
    assert(actual.progress_percent == 42.5f);
    assert(std::string(to_string(actual.lifecycle)) == "printing");
    return 0;
}
