"""Exercise provider page selection and the installer's generated configuration."""

import itertools
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FirmwarePageTests(unittest.TestCase):
    def test_installer_accepts_each_page_combination_except_empty(self):
        script = (ROOT / 'scripts/install_firmware.sh').read_text()
        config_script = script.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
        keys = ('CC_CODEX_PAGE', 'CC_OPENCODE_PAGE', 'CC_CLAUDE_PAGE',
                'CC_SYSTEM_MONITOR')
        settings = ('kShowCodexPage', 'kShowOpenCodePage', 'kShowClaudePage',
                    'kShowSystemPage')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'root'
            target = Path(tmp) / 'target'
            (root / 'firmware/app_codex/net').mkdir(parents=True)
            (target / 'main/apps/app_codex/net').mkdir(parents=True)
            for path in ('firmware/app_codex/net/net_config.h',
                         'firmware/app_codex/app_codex_config.h'):
                shutil.copyfile(ROOT / path, root / path)
            hub_config = ROOT / 'firmware/hub_wifi/hub_wifi_config.h'
            if hub_config.exists():
                (root / 'firmware/hub_wifi').mkdir(parents=True)
                (target / 'main/services/hub_wifi').mkdir(parents=True)
                shutil.copyfile(hub_config, root / 'firmware/hub_wifi/hub_wifi_config.h')
            for flags in itertools.product((False, True), repeat=4):
                with self.subTest(flags=flags):
                    env = root / '.env'
                    env.write_text('CC_LAYOUT=pages\n' + ''.join(
                        f'{key}={str(flag).lower()}\n'
                        for key, flag in zip(keys, flags)))
                    result = subprocess.run(
                        [sys.executable, '-c', config_script, str(root),
                         str(target), str(env)], capture_output=True, text=True)
                    if not any(flags):
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('requires at least one', result.stderr)
                        continue
                    self.assertEqual(result.returncode, 0, result.stderr)
                    header = (target / 'main/apps/app_codex/app_codex_config.h').read_text()
                    for setting, flag in zip(settings, flags):
                        self.assertIn(f'{setting} = {str(flag).lower()}', header)
            # Provider-page switches do not remove the classic two-row page.
            env.write_text('CC_LAYOUT=rows\n' + ''.join(f'{key}=false\n' for key in keys))
            result = subprocess.run([sys.executable, '-c', config_script,
                                     str(root), str(target), str(env)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('g++'), 'host C++ compiler required')
    def test_navigation_wraps_without_visiting_disabled_pages(self):
        app = (ROOT / 'firmware/app_codex/app_codex.cpp').read_text()
        routing = app[app.index('int page_count()'):app.index('void update_mode_label()')]
        harness = r'''
#include <cassert>
#include <initializer_list>
#include <vector>
struct lv_obj_t { bool hidden = true; };
constexpr int LV_OBJ_FLAG_HIDDEN = 1;
void lv_obj_add_flag(lv_obj_t* p, int) { p->hidden = true; }
void lv_obj_remove_flag(lv_obj_t* p, int) { p->hidden = false; }
bool kLayoutPages, kShowCodexPage, kShowOpenCodePage, kShowClaudePage, kShowSystemPage;
lv_obj_t ai, codex, opencode, claude, sys;
lv_obj_t *s_page_ai, *s_page_codex, *s_page_opencode, *s_page_claude, *s_page_sys;
int s_page;
''' + routing + r'''
int main() {
    for (int layout = 0; layout < 2; ++layout) {
        kLayoutPages = layout;
        for (int mask = 0; mask < 16; ++mask) {
            kShowCodexPage = mask & 1;
            kShowOpenCodePage = mask & 2;
            kShowClaudePage = mask & 4;
            kShowSystemPage = mask & 8;
            if (layout && !mask) continue; // Rejected by installer/static_assert.
            s_page_ai = layout ? nullptr : &ai;
            s_page_codex = layout && kShowCodexPage ? &codex : nullptr;
            s_page_opencode = layout && kShowOpenCodePage ? &opencode : nullptr;
            s_page_claude = layout && kShowClaudePage ? &claude : nullptr;
            s_page_sys = kShowSystemPage ? &sys : nullptr;
            std::vector<lv_obj_t*> expected;
            if (!layout) expected.push_back(&ai);
            else {
                if (kShowCodexPage) expected.push_back(&codex);
                if (kShowOpenCodePage) expected.push_back(&opencode);
                if (kShowClaudePage) expected.push_back(&claude);
            }
            if (kShowSystemPage) expected.push_back(&sys);
            int count = expected.size();
            assert(page_count() == count);
            for (int idx = -2 * count; idx <= 2 * count; ++idx) {
                show_page(idx);
                int wrapped = (idx % count + count) % count;
                assert(s_page == wrapped);
                assert(page_obj(s_page) == expected[wrapped]);
                for (int j = 0; j < count; ++j)
                    assert(expected[j]->hidden == (j != wrapped));
            }
        }
    }
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'navigation.cpp'
            binary = Path(tmp) / 'navigation'
            source.write_text(harness)
            subprocess.run(['g++', '-std=c++17', str(source), '-o', str(binary)],
                           check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
