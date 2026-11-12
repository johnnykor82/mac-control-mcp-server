"""FR025 C7: verified beta.29 GUI asset pin for fresh installation."""
import subprocess
import unittest
from pathlib import Path
from scripts import setup_gui_dependency as gui

RELEASE = 'v0.1.0-beta.57'
SHA256 = '35f8b056554f534f305ddb571ead2bdb916a6558086f12665a667eba1d599265'


class NativeReleasePinFR025Tests(unittest.TestCase):
    def test_pinned_archive_is_same_version_as_server_release(self):
        self.assertEqual(
            gui.RELEASE_URL,
            'https://github.com/johnnykor82/mac-control-mcp-server/releases/'
            'download/' + RELEASE + '/mac-control-native-' + RELEASE + '-universal.tar.gz',
        )
        self.assertEqual(gui.RELEASE_SHA256, SHA256)

    def test_native_download_guards_remain_strict(self):
        self.assertLess(gui.MAX_ARCHIVE, gui.MAX_EXPANDED)
        self.assertTrue(callable(gui.verify_universal))
        self.assertTrue(callable(gui._verify_payload))

    def test_source_inventory_matches_release_checkout(self):
        root = Path(__file__).resolve().parents[2]
        lines = (root / "BETA_SOURCE_MANIFEST.txt").read_text(encoding="utf-8").splitlines()
        paths = lines[4:]
        self.assertEqual(lines[2], f"Included files: {len(paths)}")
        self.assertEqual(paths, sorted(set(paths)))
        for item in paths:
            with self.subTest(path=item):
                self.assertTrue((root / item).is_file())
        if (root / ".git").exists():
            tracked = subprocess.check_output(
                ["git", "-C", str(root), "ls-files"], text=True).splitlines()
            self.assertEqual(paths, tracked)


if __name__ == '__main__':
    unittest.main()
