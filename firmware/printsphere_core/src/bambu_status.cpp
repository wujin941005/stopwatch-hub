/*
 * SPDX-FileCopyrightText: 2026 Cpt_Kirk
 *
 * SPDX-License-Identifier: LicenseRef-FNCL-1.1
 *
 * Adapted from PrintSphere v1.6.2 for StopWatch Hub.
 */
#include "printsphere/bambu_status.hpp"

#include <cctype>

namespace printsphere {

std::string normalize_bambu_status_token(const std::string& status_text) {
  std::string normalized;
  normalized.reserve(status_text.size());
  for (const char ch : status_text) {
    if (std::isalnum(static_cast<unsigned char>(ch)) != 0) {
      normalized.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(ch))));
    }
  }
  return normalized;
}

PrinterModel bambu_model_from_product_name(const std::string& product_name) {
  const std::string normalized = normalize_bambu_status_token(product_name);
  if (normalized.find("A1MINI") != std::string::npos) {
    return PrinterModel::kA1Mini;
  }
  if (normalized.find("A2L") != std::string::npos) {
    return PrinterModel::kA2L;
  }
  if (normalized.find("BAMBULABA1") != std::string::npos || normalized == "A1") {
    return PrinterModel::kA1;
  }
  if (normalized.find("P1S") != std::string::npos) {
    return PrinterModel::kP1S;
  }
  if (normalized.find("P1P") != std::string::npos) {
    return PrinterModel::kP1P;
  }
  if (normalized.find("P2S") != std::string::npos) {
    return PrinterModel::kP2S;
  }
  if (normalized.find("H2DPRO") != std::string::npos) {
    return PrinterModel::kH2DPro;
  }
  if (normalized.find("H2D") != std::string::npos) {
    return PrinterModel::kH2D;
  }
  if (normalized.find("H2S") != std::string::npos) {
    return PrinterModel::kH2S;
  }
  if (normalized.find("H2C") != std::string::npos) {
    return PrinterModel::kH2C;
  }
  if (normalized.find("X2D") != std::string::npos) {
    return PrinterModel::kX2D;
  }
  if (normalized.find("X1E") != std::string::npos) {
    return PrinterModel::kX1E;
  }
  if (normalized.find("X1CARBON") != std::string::npos ||
      normalized.find("X1C") != std::string::npos) {
    return PrinterModel::kX1C;
  }
  if (normalized.find("X1") != std::string::npos) {
    return PrinterModel::kX1;
  }
  return PrinterModel::kUnknown;
}

bool bambu_status_is_failed(const std::string& status_text) {
  const std::string normalized = normalize_bambu_status_token(status_text);
  return normalized.find("FAIL") != std::string::npos ||
         normalized.find("ERROR") != std::string::npos ||
         normalized.find("CANCEL") != std::string::npos;
}

bool bambu_status_is_finished(const std::string& status_text) {
  const std::string normalized = normalize_bambu_status_token(status_text);
  return normalized.find("DONE") != std::string::npos ||
         normalized.find("SUCCESS") != std::string::npos ||
         normalized.find("COMPLETE") != std::string::npos ||
         normalized.find("COMPLETED") != std::string::npos ||
         normalized.find("FINISH") != std::string::npos;
}

bool bambu_status_is_paused(const std::string& status_text) {
  return normalize_bambu_status_token(status_text).find("PAUSE") != std::string::npos;
}

bool bambu_status_is_preparing(const std::string& status_text) {
  const std::string normalized = normalize_bambu_status_token(status_text);
  return normalized == "INIT" || normalized == "SLICING" ||
         normalized.find("PREPARE") != std::string::npos ||
         normalized.find("PREPARING") != std::string::npos ||
         normalized.find("STARTING") != std::string::npos ||
         normalized.find("HEATING") != std::string::npos ||
         normalized.find("DOWNLOAD") != std::string::npos;
}

bool bambu_status_is_printing(const std::string& status_text) {
  const std::string normalized = normalize_bambu_status_token(status_text);
  return normalized.find("RUNNING") != std::string::npos ||
         normalized.find("PRINTING") != std::string::npos ||
         normalized.find("PROCESSING") != std::string::npos;
}

PrintLifecycleState lifecycle_from_bambu_status(const std::string& status_text,
                                                bool has_concrete_error) {
  if (has_concrete_error) {
    return PrintLifecycleState::kError;
  }

  const std::string normalized = normalize_bambu_status_token(status_text);
  if (normalized.empty() || normalized == "UNKNOWN") {
    return PrintLifecycleState::kUnknown;
  }
  if (bambu_status_is_failed(normalized)) {
    return PrintLifecycleState::kError;
  }
  if (bambu_status_is_paused(normalized)) {
    return PrintLifecycleState::kPaused;
  }
  if (bambu_status_is_preparing(normalized)) {
    return PrintLifecycleState::kPreparing;
  }
  if (bambu_status_is_printing(normalized)) {
    return PrintLifecycleState::kPrinting;
  }
  if (bambu_status_is_finished(normalized)) {
    return PrintLifecycleState::kFinished;
  }
  if (normalized.find("IDLE") != std::string::npos || normalized.find("WAIT") != std::string::npos ||
      normalized.find("OFFLINE") != std::string::npos) {
    return PrintLifecycleState::kIdle;
  }
  return PrintLifecycleState::kUnknown;
}

std::string bambu_pretty_status(const std::string& status_text) {
  const std::string normalized = normalize_bambu_status_token(status_text);
  if (normalized.empty() || normalized == "UNKNOWN") {
    return {};
  }
  if (normalized.find("DOWNLOAD") != std::string::npos) {
    return "downloading";
  }
  if (bambu_status_is_failed(normalized)) {
    return "failed";
  }
  if (bambu_status_is_finished(normalized)) {
    return "done";
  }
  if (bambu_status_is_paused(normalized)) {
    return "paused";
  }
  if (bambu_status_is_preparing(normalized)) {
    return "preparing";
  }
  if (bambu_status_is_printing(normalized)) {
    return "printing";
  }
  if (normalized.find("OFFLINE") != std::string::npos) {
    return "offline";
  }
  if (normalized.find("IDLE") != std::string::npos || normalized.find("WAIT") != std::string::npos) {
    return "idle";
  }
  return {};
}

std::string bambu_stage_label_from_id(int stage_id) {
  // Based on the currently known Bambu stage ids used by ha-bambulab.
  switch (stage_id) {
    case 0:
      return "printing";
    case 1:
      return "auto_bed_leveling";
    case 2:
      return "heatbed_preheating";
    case 3:
      return "sweeping_xy_mech_mode";
    case 4:
      return "changing_filament";
    case 5:
      return "m400_pause";
    case 6:
      return "paused_filament_runout";
    case 7:
      return "heating_hotend";
    case 8:
      return "calibrating_extrusion";
    case 9:
      return "scanning_bed_surface";
    case 10:
      return "inspecting_first_layer";
    case 11:
      return "identifying_build_plate_type";
    case 12:
      return "calibrating_micro_lidar";
    case 13:
      return "homing_toolhead";
    case 14:
      return "cleaning_nozzle_tip";
    case 15:
      return "checking_extruder_temperature";
    case 16:
      return "paused_user";
    case 17:
      return "paused_front_cover_falling";
    case 18:
      return "calibrating_micro_lidar";
    case 19:
      return "calibrating_extrusion_flow";
    case 20:
      return "paused_nozzle_temperature_malfunction";
    case 21:
      return "paused_heat_bed_temperature_malfunction";
    case 22:
      return "filament_unloading";
    case 23:
      return "paused_skipped_step";
    case 24:
      return "filament_loading";
    case 25:
      return "calibrating_motor_noise";
    case 26:
      return "paused_ams_lost";
    case 27:
      return "paused_low_fan_speed_heat_break";
    case 28:
      return "paused_chamber_temperature_control_error";
    case 29:
      return "cooling_chamber";
    case 30:
      return "paused_user_gcode";
    case 31:
      return "motor_noise_showoff";
    case 32:
      return "paused_nozzle_filament_covered_detected";
    case 33:
      return "paused_cutter_error";
    case 34:
      return "paused_first_layer_error";
    case 35:
      return "paused_nozzle_clog";
    case 36:
      return "check_absolute_accuracy_before_calibration";
    case 37:
      return "absolute_accuracy_calibration";
    case 38:
      return "check_absolute_accuracy_after_calibration";
    case 39:
      return "calibrate_nozzle_offset";
    case 40:
      return "bed_level_high_temperature";
    case 41:
      return "check_quick_release";
    case 42:
      return "check_door_and_cover";
    case 43:
      return "laser_calibration";
    case 44:
      return "check_plaform";
    case 45:
      return "check_birdeye_camera_position";
    case 46:
      return "calibrate_birdeye_camera";
    case 47:
      return "bed_level_phase_1";
    case 48:
      return "bed_level_phase_2";
    case 49:
      return "heating_chamber";
    case 50:
      return "heated_bedcooling";
    case 51:
      return "print_calibration_lines";
    case 52:
      return "check_material";
    case 53:
      return "calibrating_live_view_camera";
    case 54:
      return "waiting_for_heatbed_temperature";
    case 55:
      return "check_material_position";
    case 56:
      return "calibrating_cutter_model_offset";
    case 57:
      return "measuring_surface";
    case 58:
      return "thermal_preconditioning";
    case 59:
      return "homing_blade_holder";
    case 60:
      return "calibrating_camera_offset";
    case 61:
      return "calibrating_blade_holder_position";
    case 62:
      return "hotend_pick_place_test";
    case 63:
      return "waiting_chamber_temperature_equalize";
    case 64:
      return "preparing_hotend";
    case 65:
      return "calibrating_detection_nozzle_clumping";
    case 66:
      return "purifying_chamber_air";
    case 77:
      return "preparing_ams";
    case -1:
    case 255:
      return "idle";
    default:
      return {};
  }
}

std::string bambu_default_stage_label_for_status(const std::string& status_text,
                                                 bool has_concrete_error) {
  const std::string normalized = normalize_bambu_status_token(status_text);
  if (normalized.empty()) {
    return "Status";
  }
  if (normalized.find("DOWNLOAD") != std::string::npos) {
    return "Model Download";
  }
  if (bambu_status_is_printing(normalized)) {
    return "Printing";
  }
  if (bambu_status_is_preparing(normalized)) {
    return "Preparing";
  }
  if (bambu_status_is_paused(normalized)) {
    return "Paused";
  }
  if (bambu_status_is_finished(normalized)) {
    return "Finished";
  }
  if (normalized.find("IDLE") != std::string::npos) {
    return "Idle";
  }
  if (normalized.find("OFFLINE") != std::string::npos) {
    return "Offline";
  }
  if (bambu_status_is_failed(normalized)) {
    return has_concrete_error ? "Failed" : "Stopped";
  }
  return "Status";
}

}  // namespace printsphere
