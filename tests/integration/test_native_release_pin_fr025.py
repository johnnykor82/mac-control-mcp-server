"""FR025 C7: verified beta.29 GUI asset pin for fresh installation."""
import unittest
from scripts import setup_gui_dependency as gui

RELEASE = 'v0.1.0-beta.29'
SHA256 = '7c1e99163d3c765492f3b035daf609b43092c28ea1380f4c4886b655fdf156ad'


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


if __name__ == '__main__':
    unittest.main()
