import importlib.util
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path


BRIDGE_PATH = Path(__file__).parents[1] / "bridge" / "codexisland_bridge.py"
SPEC = importlib.util.spec_from_file_location("cc_island_bridge", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class ProviderTests(unittest.TestCase):
    def test_codex_transport_error_is_not_reported_as_http_zero(self):
        auth = '{"tokens":{"access_token":"test-token"}}'
        transport = {
            "_transport_error":
                "<urlopen error [Errno 101] Network is unreachable>"
        }
        with mock.patch.object(bridge, "_codex_roots", return_value=["/tmp/.codex"]), \
                mock.patch("builtins.open", mock.mock_open(read_data=auth)), \
                mock.patch.object(bridge, "_http", return_value=(0, transport)):
            self.assertEqual(
                bridge.fetch_codex(),
                {"error": "network unreachable"},
            )

    def test_claude_credentials_file_supports_linux_and_windows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".credentials.json"
            path.write_text(json.dumps({
                "claudeAiOauth": {
                    "accessToken": "access",
                    "refreshToken": "refresh",
                    "subscriptionType": "max",
                },
            }))
            with mock.patch.object(bridge, "_claude_roots", return_value=[tmpdir]):
                creds = bridge._read_claude_file_creds()
            self.assertEqual(creds["source"], "file")
            self.assertEqual(creds["oauth"]["accessToken"], "access")

    def test_claude_credentials_refresh_is_written_back_atomically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".credentials.json"
            path.write_text(json.dumps({
                "unrelated": {"keep": True},
                "claudeAiOauth": {"accessToken": "old"},
            }))
            oauth = {
                "accessToken": "new-access",
                "refreshToken": "new-refresh",
                "expiresAt": 123,
            }

            self.assertTrue(bridge._write_claude_file_creds(str(path), oauth))
            saved = json.loads(path.read_text())
            self.assertEqual(saved["unrelated"], {"keep": True})
            self.assertEqual(saved["claudeAiOauth"], oauth)
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])


class PlatformPathTests(unittest.TestCase):
    def test_windows_paths_are_translated_when_bridge_runs_in_wsl(self):
        with mock.patch.object(bridge, "_is_wsl", return_value=True):
            self.assertEqual(
                bridge._windows_to_wsl_path(
                    r"C:\Users\Alice\.local\share\opencode\opencode.db"
                ),
                "/mnt/c/Users/Alice/.local/share/opencode/opencode.db",
            )

    def test_opencode_database_uses_xdg_then_channel_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data = Path(tmpdir) / "data" / "opencode"
            data.mkdir(parents=True)
            beta = data / "opencode-beta.db"
            beta.touch()
            with mock.patch.dict(
                os.environ,
                {"XDG_DATA_HOME": str(Path(tmpdir) / "data")},
                clear=True,
            ), mock.patch.object(bridge, "_host_homes", return_value=[]):
                self.assertEqual(bridge._find_opencode_db(), str(beta))

                stable = data / "opencode.db"
                stable.touch()
                self.assertEqual(bridge._find_opencode_db(), str(stable))

    def test_explicit_opencode_database_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "custom.db"
            path.touch()
            with mock.patch.dict(
                os.environ, {"OPENCODE_DB": str(path)}, clear=True
            ):
                self.assertEqual(bridge._find_opencode_db(), str(path))


class PricingTests(unittest.TestCase):
    def test_parse_openrouter_prices_and_cache_fallbacks(self):
        catalog = bridge._parse_openrouter_pricing({
            "data": [
                {
                    "id": "openai/example",
                    "pricing": {
                        "prompt": "0.000001",
                        "completion": "0.000006",
                        "input_cache_read": "0.0000001",
                        "input_cache_write": "0.00000125",
                    },
                },
                {
                    "id": "anthropic/example",
                    "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                },
                {
                    "id": "openai/not-priced",
                    "pricing": {"prompt": "-1", "completion": "-1"},
                },
                {
                    "id": "deepseek/free-example",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
                {
                    "id": "invalid-without-owner",
                    "pricing": {"prompt": "0", "completion": "0"},
                },
            ],
        })

        expected_openai = (1.0, 6.0, 1.25, 0.1)
        for actual, expected in zip(catalog["openai/example"], expected_openai):
            self.assertAlmostEqual(actual, expected)
        expected_anthropic = (3.0, 15.0, 3.0, 3.0)
        for actual, expected in zip(catalog["anthropic/example"], expected_anthropic):
            self.assertAlmostEqual(actual, expected)
        self.assertNotIn("openai/not-priced", catalog)
        self.assertEqual(catalog["deepseek/free-example"], (0.0, 0.0, 0.0, 0.0))
        self.assertNotIn("invalid-without-owner", catalog)

    def test_model_candidates_cover_provider_spelling_dates_and_auto_review(self):
        self.assertEqual(
            bridge._model_price_candidates("anthropic", "claude-opus-4-8-20260528"),
            [
                "anthropic/claude-opus-4-8-20260528",
                "anthropic/claude-opus-4.8-20260528",
                "anthropic/claude-opus-4-8",
                "anthropic/claude-opus-4.8",
            ],
        )
        self.assertEqual(
            bridge._model_price_candidates("openai", "gpt-5.6-sol-2026-07-09"),
            ["openai/gpt-5.6-sol-2026-07-09", "openai/gpt-5.6-sol"],
        )
        self.assertIn(
            "openai/gpt-5.6-sol",
            bridge._model_price_candidates("openai", "codex-auto-review"),
        )

    def test_catalog_aliases_cover_opencode_subscription_provider_ids(self):
        catalog = {
            "deepseek/deepseek-v4-flash": (0.14, 0.28, 0.14, 0.028),
            "moonshotai/kimi-k3": (3.0, 15.0, 3.0, 0.3),
        }
        key, rates = bridge._catalog_rate(
            catalog,
            bridge._model_price_candidates("opencode-go", "deepseek-v4-flash"),
        )
        self.assertEqual(key, "deepseek/deepseek-v4-flash")
        self.assertEqual(rates, catalog[key])

        key, rates = bridge._catalog_rate(
            catalog,
            bridge._model_price_candidates("tu-zi", "coding-kimi-k3"),
        )
        self.assertEqual(key, "moonshotai/kimi-k3")
        self.assertEqual(rates, catalog[key])

    def test_cost_uses_dynamic_catalog(self):
        previous = (
            bridge._PRICE_CATALOG,
            bridge._PRICE_CATALOG_FETCHED_AT,
            bridge._PRICE_CATALOG_LOADED,
        )
        try:
            bridge._PRICE_CATALOG = {"openai/example": (1.0, 6.0, 1.25, 0.1)}
            bridge._PRICE_CATALOG_FETCHED_AT = time.time()
            bridge._PRICE_CATALOG_LOADED = True
            cost = bridge._cost("openai", "example", 1_000_000, 1_000_000,
                                1_000_000, 1_000_000)
            self.assertAlmostEqual(cost, 8.35)
        finally:
            (bridge._PRICE_CATALOG,
             bridge._PRICE_CATALOG_FETCHED_AT,
             bridge._PRICE_CATALOG_LOADED) = previous

    def test_last_good_catalog_round_trip(self):
        previous_env = os.environ.get("CC_PRICING_CACHE")
        previous = (
            bridge._PRICE_CATALOG,
            bridge._PRICE_CATALOG_FETCHED_AT,
            bridge._PRICE_CATALOG_LOADED,
            bridge._PRICE_CATALOG_SOURCE,
        )
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "prices.json"
                os.environ["CC_PRICING_CACHE"] = str(path)
                bridge._PRICE_CATALOG = {"openai/example": (1.0, 2.0, 3.0, 4.0)}
                bridge._PRICE_CATALOG_FETCHED_AT = 123.0
                bridge._save_price_cache_unlocked()

                bridge._PRICE_CATALOG = {}
                bridge._PRICE_CATALOG_FETCHED_AT = 0.0
                bridge._PRICE_CATALOG_LOADED = False
                bridge._load_price_cache_unlocked()

                self.assertEqual(
                    bridge._PRICE_CATALOG["openai/example"],
                    (1.0, 2.0, 3.0, 4.0),
                )
                self.assertEqual(bridge._PRICE_CATALOG_FETCHED_AT, 123.0)
                self.assertEqual(bridge._PRICE_CATALOG_SOURCE, "disk-cache")
        finally:
            if previous_env is None:
                os.environ.pop("CC_PRICING_CACHE", None)
            else:
                os.environ["CC_PRICING_CACHE"] = previous_env
            (bridge._PRICE_CATALOG,
             bridge._PRICE_CATALOG_FETCHED_AT,
             bridge._PRICE_CATALOG_LOADED,
             bridge._PRICE_CATALOG_SOURCE) = previous


class OpenCodeTests(unittest.TestCase):
    def test_message_usage_reprices_plan_tokens_and_deduplicates_calls(self):
        con = sqlite3.connect(":memory:")
        con.executescript(
            """
            CREATE TABLE session (id TEXT PRIMARY KEY, time_updated INTEGER NOT NULL);
            CREATE TABLE message (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                time_created INTEGER NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX message_session_time_created_id_idx
                ON message (session_id, time_created, id);
            """
        )
        today = 10_000_000
        week = 4_000_000
        con.execute("INSERT INTO session VALUES (?, ?)", ("old-session", today + 10))

        def add(message_id, created, role, cost):
            data = {
                "role": role,
                "cost": cost,
                "providerID": "openai",
                "modelID": "example",
                "tokens": {
                    "input": 1_000_000,
                    "output": 2_000_000,
                    "reasoning": 3_000_000,
                    "cache": {"read": 4_000_000, "write": 5_000_000},
                },
            }
            con.execute("INSERT INTO message VALUES (?, ?, ?, ?)",
                        (message_id, "old-session", created, json.dumps(data)))

        add("week", week + 1, "assistant", 2.0)
        add("today", today + 1, "assistant", 1.25)
        # Same upstream call recorded under another message id: count once.
        add("today-duplicate", today + 1, "assistant", 1.25)
        add("user", today + 2, "user", 99.0)
        con.execute("INSERT INTO message VALUES (?, ?, ?, ?)",
                    ("invalid", "old-session", today + 3, "not-json"))

        rates = (1.0, 6.0, 1.25, 0.1)
        with mock.patch.object(bridge, "_price_rates", return_value=rates):
            usage = bridge._opencode_message_usage(con, today, week)
        self.assertEqual(usage["sessions"], 1)
        self.assertEqual(usage["tokens"], 15_000_000)
        self.assertAlmostEqual(usage["cost"], 37.65)
        self.assertAlmostEqual(usage["week_cost"], 75.30)
        self.assertAlmostEqual(usage["actual_cost"], 1.25)
        self.assertAlmostEqual(usage["week_actual_cost"], 3.25)
        self.assertEqual(usage["cost_source"], "openrouter")

        # Unknown models retain OpenCode's recorded amount instead of
        # disappearing from the dollar total.
        with mock.patch.object(bridge, "_price_rates", return_value=None):
            fallback = bridge._opencode_message_usage(con, today, week)
        self.assertAlmostEqual(fallback["cost"], 1.25)
        self.assertAlmostEqual(fallback["week_cost"], 3.25)
        self.assertEqual(fallback["cost_source"], "recorded")
        con.close()

    def test_compact_does_not_mutate_opencode_cache(self):
        data = {
            "claude": {"five_hour": None, "weekly": None},
            "codex": {"five_hour": None, "weekly": None},
            "opencode": {
                "t": 0.03,
                "T": 2_478_497,
                "s": 2,
                "d": 21.03,
                "source": "messages",
                "go": {"h": 12, "hr": 30, "w": 34, "wr": 60},
            },
            "sys": {"cpu": 1, "mem": 2, "disk": 3},
        }
        before = json.dumps(data, sort_keys=True)
        payload = json.loads(bridge.compact(data))

        self.assertEqual(json.dumps(data, sort_keys=True), before)
        self.assertEqual(payload["o"]["T"], 2_478_497)
        self.assertEqual(payload["o"]["hr"], 30)
        self.assertNotIn("source", payload["o"])
        self.assertNotIn("go", payload["o"])


class SystemMonitorTests(unittest.TestCase):
    def test_env_bool(self):
        with mock.patch.dict(os.environ, {"CC_SYSTEM_MONITOR": "YES"}):
            self.assertTrue(bridge.system_monitor_enabled())
        with mock.patch.dict(os.environ, {"CC_SYSTEM_MONITOR": "off"}):
            self.assertFalse(bridge.system_monitor_enabled())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(bridge.system_monitor_enabled())

    def test_collect_skips_host_stats_when_disabled(self):
        previous_cache = bridge._DATA_CACHE
        providers = {
            "ts": 1,
            "claude": {"five_hour": None, "weekly": None},
            "codex": {"five_hour": None, "weekly": None},
            "opencode": {"t": 0, "T": 0, "s": 0, "d": 0},
        }
        try:
            bridge._DATA_CACHE = dict(providers)
            with mock.patch.dict(os.environ, {"CC_SYSTEM_MONITOR": "false"}), \
                    mock.patch.object(bridge, "sys_stats") as stats:
                data = bridge.collect()
            self.assertNotIn("sys", data)
            stats.assert_not_called()
        finally:
            bridge._DATA_CACHE = previous_cache

    def test_collect_includes_host_stats_when_enabled(self):
        previous_cache = bridge._DATA_CACHE
        providers = {
            "ts": 1,
            "claude": {"five_hour": None, "weekly": None},
            "codex": {"five_hour": None, "weekly": None},
            "opencode": {"t": 0, "T": 0, "s": 0, "d": 0},
        }
        try:
            bridge._DATA_CACHE = dict(providers)
            with mock.patch.dict(os.environ, {"CC_SYSTEM_MONITOR": "true"}), \
                    mock.patch.object(
                        bridge, "sys_stats", return_value={"cpu": 12.3}
                    ) as stats:
                data = bridge.collect()
            self.assertEqual(data["sys"], {"cpu": 12.3})
            stats.assert_called_once_with()
        finally:
            bridge._DATA_CACHE = previous_cache

    def test_macos_vm_stat_parser(self):
        output = """Mach Virtual Memory Statistics: (page size of 4096 bytes)\nPages free: 10.\nPages active: 60.\nPages inactive: 20.\nPages speculative: 5.\n"""
        self.assertEqual(bridge._parse_vm_stat(output, 100 * 4096), 65.0)

    def test_platform_system_backend_dispatch(self):
        mac = {"name": "Mac", "cpu": 1}
        with mock.patch.object(bridge.os, "name", "posix"), \
                mock.patch.object(bridge.sys, "platform", "darwin"), \
                mock.patch.object(bridge, "_is_wsl", return_value=False), \
                mock.patch.object(bridge, "_macos_sys_stats", return_value=mac):
            self.assertEqual(bridge._collect_system_stats(), mac)

        native_windows = {"name": "PC", "cpu": 2}
        with mock.patch.object(bridge.os, "name", "nt"), \
                mock.patch.object(
                    bridge, "_psutil_sys_stats", return_value=native_windows
                ) as psutil_stats, \
                mock.patch.object(bridge, "_windows_sys_stats") as powershell:
            self.assertEqual(bridge._collect_system_stats(), native_windows)
            psutil_stats.assert_called_once_with()
            powershell.assert_not_called()

        wsl_windows = {"name": "PC", "cpu": 3}
        with mock.patch.object(bridge.os, "name", "posix"), \
                mock.patch.object(bridge, "_is_wsl", return_value=True), \
                mock.patch.object(
                    bridge, "_windows_sys_stats", return_value=wsl_windows
                ):
            self.assertEqual(bridge._collect_system_stats(), wsl_windows)


if __name__ == "__main__":
    unittest.main()
