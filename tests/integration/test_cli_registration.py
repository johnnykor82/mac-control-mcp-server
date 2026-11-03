"""Regression tests for user-visible mclog/maccontrol CLI registration."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import setup_cli_commands as cli


class CliRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve() / "owner"
        self.home.mkdir()
        self.root = self.home / "MacControlMCP"
        (self.root / "current/bin").mkdir(parents=True)
        (self.root / "bin").mkdir()
        for command in ("mclog", "maccontrol"):
            path = self.root / ("current/bin/mclog" if command == "mclog" else "bin/maccontrol")
            path.write_text('#!/bin/sh\nprintf "%s\\n" ' + command + '\n')
            path.chmod(0o700)

    def register(self, path="/usr/bin:/bin"):
        return cli.register(self.root, home=self.home, environ={"PATH": path})

    def test_mclog_and_maccontrol_work_via_path_without_sudo(self):
        result = self.register()
        self.assertEqual(result["path"], "added_to_zprofile")
        self.assertEqual(result["mclog"], "registered")
        self.assertEqual(result["maccontrol"], "registered")
        self.assertTrue((self.home / ".zprofile").exists())
        for command in ("mclog", "maccontrol"):
            output = subprocess.check_output(
                [command], text=True, env={**os.environ,
                    "PATH": str(self.home / ".local/bin") + ":/usr/bin:/bin"})
            self.assertEqual(output.strip(), command)

    def test_registration_is_idempotent_and_uninstall_clean(self):
        first = self.register()
        original = (self.home / ".zprofile").read_text()
        second = self.register()
        self.assertEqual(second["mclog"], "already_registered")
        self.assertEqual(second["maccontrol"], "already_registered")
        self.assertEqual((self.home / ".zprofile").read_text(), original)
        removed = cli.unregister(self.root, home=self.home)
        self.assertEqual(removed["mclog"], "removed")
        self.assertEqual(removed["maccontrol"], "removed")
        self.assertEqual(removed["root_mclog"], "removed")
        self.assertNotIn(cli.START, (self.home / ".zprofile").read_text())
        self.assertEqual(cli.unregister(self.root, home=self.home)["mclog"], "preserved")

    def test_preserve_foreign_user_command_and_existing_profile(self):
        bin_dir = self.home / ".local/bin"
        bin_dir.mkdir(parents=True)
        foreign = bin_dir / "mclog"
        foreign.write_text("#!/bin/sh\necho FOREIGN\n")
        existing = self.home / ".zprofile"
        existing.write_text("# my profile\nexport TEST=1\n")
        result = self.register()
        self.assertEqual(result["mclog"], "conflict")
        self.assertEqual(result["mclog_resolution"]["status"], "approval_required")
        self.assertIn("FOREIGN", foreign.read_text())
        self.assertEqual(result["maccontrol"], "registered")
        self.assertTrue(existing.read_text().startswith("# my profile\nexport TEST=1\n"))
        cli.unregister(self.root, home=self.home)
        self.assertEqual(foreign.read_text(), "#!/bin/sh\necho FOREIGN\n")
        self.assertEqual(existing.read_text(), "# my profile\nexport TEST=1\n")

    def test_refuse_foreign_symlink_without_following(self):
        outside = self.home / "outside"
        outside.write_text("protected")
        userbin = self.home / ".local/bin"
        userbin.mkdir(parents=True)
        (userbin / "mclog").symlink_to(outside)
        result = self.register()
        self.assertEqual(result["mclog"], "conflict")
        cli.unregister(self.root, home=self.home)
        self.assertTrue((userbin / "mclog").is_symlink())
        self.assertEqual(outside.read_text(), "protected")

    def test_executable_handles_paths_with_spaces_and_metacharacters(self):
        spaced = self.home / "Mac Control (beta) & Spaces"
        self.root.rename(spaced)
        self.root = spaced
        self.register()
        output = subprocess.check_output(["mclog"], text=True, env={**os.environ,
            "PATH": str(self.home / ".local/bin") + ":/usr/bin:/bin"})
        self.assertEqual(output.strip(), "mclog")

    def test_already_in_path_does_not_mutate_zprofile(self):
        result = self.register(path=str(self.home / ".local/bin") + ":/usr/bin")
        self.assertEqual(result["path"], "already_in_path")
        self.assertFalse((self.home / ".zprofile").exists())

    def test_uninstall_does_not_delete_user_edited_launcher(self):
        self.register()
        shim = self.home / ".local/bin/mclog"
        shim.write_text("#!/bin/sh\necho CUSTOM\n")
        cli.unregister(self.root, home=self.home)
        self.assertEqual(shim.read_text(), "#!/bin/sh\necho CUSTOM\n")


if __name__ == "__main__":
    unittest.main()
