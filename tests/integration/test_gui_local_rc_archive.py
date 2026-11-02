"""E9: explicit owner-pinned local GUI RC archive cannot bypass integrity checks."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import setup_gui_dependency as gui


class LocalGuiArchiveTests(unittest.TestCase):
    def setUp(self):
        scope = tempfile.TemporaryDirectory()
        self.addCleanup(scope.cleanup)
        self.root = Path(scope.name)
        self.archive = self.root / 'rc.tar.gz'
        self.archive.write_bytes(b'fixture-validated-upstream-release')
        self.archive.chmod(0o600)
        self.target = self.root / 'download.tar.gz'

    def env(self, sha):
        return patch.dict(os.environ, {
            'MACCONTROL_GUI_RC_ARCHIVE': str(self.archive),
            'MACCONTROL_GUI_RC_SHA256': sha,
        })

    def test_owner_pinned_local_archive_matches_exact_bytes(self):
        with self.env(hashlib.sha256(self.archive.read_bytes()).hexdigest()):
            gui._download(self.target)
        self.assertEqual(self.target.read_bytes(), self.archive.read_bytes())

    def test_mismatched_digest_fails_without_installed_archive(self):
        with self.env('0' * 64):
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                gui._download(self.target)
        self.assertFalse(self.target.exists())

    def test_missing_explicit_hash_is_rejected(self):
        with patch.dict(os.environ, {'MACCONTROL_GUI_RC_ARCHIVE': str(self.archive)}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                gui._download(self.target)
        self.assertFalse(self.target.exists())

    def test_archive_symlink_is_refused(self):
        link = self.root / 'rc-link.tar.gz'
        link.symlink_to(self.archive)
        with patch.dict(os.environ, {
            'MACCONTROL_GUI_RC_ARCHIVE': str(link),
            'MACCONTROL_GUI_RC_SHA256': hashlib.sha256(self.archive.read_bytes()).hexdigest(),
        }):
            with self.assertRaisesRegex(RuntimeError, 'symlink|regular'):
                gui._download(self.target)
        self.assertFalse(self.target.exists())

    def test_group_writable_archive_is_refused(self):
        self.archive.chmod(0o666)
        with self.env(hashlib.sha256(self.archive.read_bytes()).hexdigest()):
            with self.assertRaisesRegex(RuntimeError, 'permissions'):
                gui._download(self.target)
        self.assertFalse(self.target.exists())


if __name__ == '__main__':
    unittest.main()
