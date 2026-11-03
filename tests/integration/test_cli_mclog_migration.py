"""E7: existing mclog survives until the owner explicitly approves migration."""
from pathlib import Path
import tempfile
import unittest

from scripts import setup_cli_commands as cli


class MclogMigrationTests(unittest.TestCase):
    def test_no_approval_preserves_legacy_and_explains_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "MacControlMCP"
            (root / "bin").mkdir(parents=True)
            (root / "current/bin").mkdir(parents=True)
            previous = home / ".local/bin/mclog"
            previous.parent.mkdir(parents=True)
            previous.write_text("#!/bin/sh\necho OLD\n")
            status = cli.resolve_mclog_conflict(root, home=home, approved=False)
            self.assertEqual(status["status"], "approval_required")
            self.assertEqual(previous.read_text(), "#!/bin/sh\necho OLD\n")

    def test_approved_migration_keeps_old_executable_under_distinct_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            root = home / "MacControlMCP"
            (root / "bin").mkdir(parents=True)
            (root / "current/bin").mkdir(parents=True)
            previous = home / ".local/bin/mclog"
            previous.parent.mkdir(parents=True)
            previous.write_text("#!/bin/sh\necho OLD\n")
            result = cli.resolve_mclog_conflict(root, home=home, approved=True)
            self.assertEqual(result["status"], "migrated")
            self.assertEqual((home / ".local/bin/mclog-legacy").read_text(),
                             "#!/bin/sh\necho OLD\n")
            self.assertEqual(previous.read_text(), cli.wrapper(root.resolve(), "mclog"))


if __name__ == "__main__":
    unittest.main()
