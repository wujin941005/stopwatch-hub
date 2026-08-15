/*
 * SPDX-FileCopyrightText: 2026 Cpt_Kirk
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 *
 * Adapted from PrintSphere v1.6.2 for StopWatch Hub.
 */
#pragma once

#include <string>

#include "printsphere/printer_state.hpp"

namespace printsphere {

std::string normalize_bambu_status_token(const std::string& status_text);
PrinterModel bambu_model_from_product_name(const std::string& product_name);
bool bambu_status_is_failed(const std::string& status_text);
bool bambu_status_is_finished(const std::string& status_text);
bool bambu_status_is_paused(const std::string& status_text);
bool bambu_status_is_preparing(const std::string& status_text);
bool bambu_status_is_printing(const std::string& status_text);
PrintLifecycleState lifecycle_from_bambu_status(const std::string& status_text,
                                                bool has_concrete_error = false);
std::string bambu_pretty_status(const std::string& status_text);
std::string bambu_stage_label_from_id(int stage_id);
std::string bambu_default_stage_label_for_status(const std::string& status_text,
                                                 bool has_concrete_error = false);

}  // namespace printsphere
