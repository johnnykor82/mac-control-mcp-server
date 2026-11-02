"""E9 distribution metadata and reproducible installation payload evidence."""
from __future__ import annotations

import hashlib
from email.message import Message
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import release_dependency_audit, release_payload_audit


class FakeDistribution:
    def __init__(self, name, version, expression="MIT"):
        self.metadata = Message()
        self.metadata["Name"] = name
        if expression:
            self.metadata["License-Expression"] = expression
        self.version = version


class DependencyAuditTests(unittest.TestCase):
    def test_jaraco_dot_names_normalized_to_pinned_dashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            req = Path(temporary) / 'deps.txt'
            req.write_text('jaraco-classes==3.4.0\njaraco-context==6.4.0\n')
            dist = [FakeDistribution('jaraco.classes', '3.4.0'),
                    FakeDistribution('jaraco.context', '6.4.0')]
            with patch.object(release_dependency_audit.metadata, 'distributions', return_value=dist):
                result = release_dependency_audit.audit_requirements(req)
            self.assertEqual(result['pinned_count'], 2)
            self.assertEqual(result['unresolved'], [])
            self.assertEqual(result['mismatched_versions'], [])

    def test_unknown_license_is_not_reported_cleared(self):
        with tempfile.TemporaryDirectory() as temporary:
            req = Path(temporary) / 'deps.txt'
            req.write_text('hypothetical==0.1\n')
            with patch.object(release_dependency_audit.metadata, 'distributions',
                              return_value=[FakeDistribution('hypothetical', '0.1', '')]):
                result = release_dependency_audit.audit_requirements(req)
            self.assertEqual(result['unresolved'], ['hypothetical'])

    def test_version_mismatch_is_not_reported_cleared(self):
        with tempfile.TemporaryDirectory() as temporary:
            req = Path(temporary) / 'deps.txt'
            req.write_text('sample==1.2.3\n')
            with patch.object(release_dependency_audit.metadata, 'distributions',
                              return_value=[FakeDistribution('sample', '1.2.4')]):
                result = release_dependency_audit.audit_requirements(req)
            self.assertEqual(result['mismatched_versions'], ['sample'])

    def test_duplicate_pin_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            req = Path(temporary) / 'deps.txt'
            req.write_text('foo.bar==1.0\nfoo-bar==2.0\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                release_dependency_audit.audit_requirements(req)


class PayloadAuditTests(unittest.TestCase):
    def test_identical_sources_produce_identical_archive_and_sha(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            (source / 'scripts').mkdir(parents=True)
            (source / 'scripts/install_manifest.txt').write_text(
                'scripts/install_manifest.txt\nscripts/payload.py\n')
            (source / 'scripts/payload.py').write_text('VALUE = 1\n')
            (source / 'scripts/.env').write_text('not distributable')
            one = release_payload_audit.build_archive(source)
            two = release_payload_audit.build_archive(source)
            self.assertEqual(one, two)
            self.assertEqual(hashlib.sha256(one).hexdigest(), hashlib.sha256(two).hexdigest())
            reviewed = release_payload_audit.inspect_archive(one, source)
            self.assertEqual(reviewed['files'], 2)
            self.assertNotIn(b'not distributable', one)

    def test_mutated_manifest_content_changes_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'scripts').mkdir()
            (source / 'scripts/install_manifest.txt').write_text('scripts/a.py\n')
            (source / 'scripts/a.py').write_text('x=1\n')
            first = release_payload_audit.build_archive(source)
            (source / 'scripts/a.py').write_text('x=2\n')
            self.assertNotEqual(first, release_payload_audit.build_archive(source))

    def test_rejects_symlink_and_duplicate_manifest_entries(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / 'scripts').mkdir()
            (source / 'scripts/a.py').write_text('x')
            manifest = source / 'scripts/install_manifest.txt'
            manifest.write_text('scripts/a.py\nscripts/a.py\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                release_payload_audit.build_archive(source)
            manifest.write_text('scripts/a.py\n')
            (source / 'scripts/a.py').rename(source / 'scripts/b.py')
            (source / 'scripts/a.py').symlink_to('b.py')
            with self.assertRaisesRegex(ValueError, 'symlink'):
                release_payload_audit.build_archive(source)


if __name__ == '__main__':
    unittest.main()
