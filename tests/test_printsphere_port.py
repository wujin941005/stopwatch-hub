import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PORT_SCRIPT = ROOT / "scripts" / "prepare_printsphere_port.py"
SPEC = importlib.util.spec_from_file_location("prepare_printsphere_port", PORT_SCRIPT)
port = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(port)


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


class PrintSpherePortTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.target = Path(self.tempdir.name)
        port.materialize(ROOT, self.target)
        self.upstream = ROOT / "vendor" / "PrintSphere" / "main"
        self.generated = self.target / "main" / "services" / "printsphere"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_full_include_and_source_inventory_is_preserved(self):
        expected = {
            path.relative_to(self.upstream)
            for folder in ("include", "src")
            for path in (self.upstream / folder).rglob("*")
            if path.is_file()
        }
        actual = {
            path.relative_to(self.generated)
            for path in self.generated.rglob("*")
            if path.is_file()
        }
        self.assertEqual(actual, expected)

    def test_board_global_owners_are_replaced_by_hub_adapters(self):
        wifi = (self.generated / "src/wifi_manager.cpp").read_text()
        pmu = (self.generated / "src/pmu.cpp").read_text()
        audio = (self.generated / "src/audio_notifier.cpp").read_text()
        ui = (self.generated / "src/ui.cpp").read_text()
        application = (self.generated / "src/application.cpp").read_text()

        self.assertIn("hub_wifi::configure_station", wifi)
        self.assertNotIn("esp_wifi_init", wifi)
        self.assertIn("GetHAL().getBatteryLevel()", pmu)
        self.assertNotIn("XPowers", pmu)
        self.assertIn("GetHAL().audioPlay", audio)
        self.assertNotIn("bsp_audio_codec_speaker_init", audio)
        self.assertIn("lv_display_get_default", ui)
        self.assertIn("lv_display_set_rotation", ui)
        self.assertNotIn("bsp_display_start_with_config", ui)
        self.assertIn("/spiflash/printsphere/sounds", application)
        self.assertIn("time_sync::start_sntp_if_needed", application)

    def test_mooncake_lifecycle_and_combined_ota_policy_are_present(self):
        application = (self.generated / "src/application.cpp").read_text()
        setup = (self.generated / "src/setup_portal.cpp").read_text()
        serial = (self.generated / "src/serial_provisioner.cpp").read_text()

        self.assertIn("Application::resume()", application)
        self.assertIn("Application::suspend()", application)
        self.assertIn("camera_client_.set_enabled(false)", application)
        self.assertIn("config.server_port = 8080", setup)
        self.assertEqual(setup.count('project_name, "StopWatch-UserDemo"'), 2)
        self.assertIn('"http://" + ip + ":8080/"', serial)

    def test_materialization_is_idempotent(self):
        first = tree_digest(self.generated)
        port.materialize(ROOT, self.target)
        self.assertEqual(tree_digest(self.generated), first)


if __name__ == "__main__":
    unittest.main()
