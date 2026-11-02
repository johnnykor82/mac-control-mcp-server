"""E7: installed tool names never silently disappear due to a feature flag."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mac_control import dev_enabled_operations as enabled


class InstalledToolVisibilityTests(unittest.TestCase):
    def test_standard_tools_remain_registered_when_component_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "feature_flags.json").write_text(json.dumps({
                "watcher": False, "native_gui": False, "background_browser": False
            }))
            with patch.dict(os.environ, {"MAC_CONTROL_DATA_ROOT": str(data)}), \
                 patch.object(enabled, "DATA_ROOT", data):
                for tool in ("watcher_status", "gui_screenshot", "chrome_chat_read"):
                    with self.subTest(tool=tool):
                        self.assertTrue(enabled.operation_enabled(tool))


if __name__ == "__main__":
    unittest.main()
