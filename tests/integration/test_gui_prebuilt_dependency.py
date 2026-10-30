"""Pinned native helpers install without local developer tools or network tests."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import plistlib
import struct
import signal
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import setup_gui_dependency as dependency
from scripts import build_mac_control_gui as gui


def universal():
    return struct.pack('>II', 0xcafebabe, 2) + b''.join(
        struct.pack('>IIIII', cpu, 0, 48 + i * 4, 4, 0)
        for i, cpu in enumerate((0x01000007, 0x0100000c))) + b'xxxx' * 2


def archive_bytes(extra=None):
    files = {
        gui.APP_NAME + '/Contents/Info.plist': plistlib.dumps({
            'CFBundleIdentifier': gui.BUNDLE, 'CFBundleExecutable': gui.EXEC_NAME}),
        gui.APP_NAME + '/Contents/MacOS/' + gui.EXEC_NAME: universal(),
        'gui_clipboard_paste': universal(),
    }
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        if extra:
            archive.addfile(extra)
    return stream.getvalue()


class Response(io.BytesIO):
    def geturl(self):
        return dependency.RELEASE_URL


class PrebuiltTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'root'
        self.release = self.root / 'releases/test'
        self.release.mkdir(parents=True)
        (self.root / 'data').mkdir()
        self.home = self.base / 'home'
        self.start(patch.object(Path, 'home', return_value=self.home))
        self.commands = []
        def run(argv, **kwargs):
            self.commands.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout='')
        self.start(patch.object(subprocess, 'run', side_effect=run))
        self.payload = archive_bytes()
        self.start(patch.object(dependency, 'RELEASE_SHA256', hashlib.sha256(self.payload).hexdigest()))
        self.download = self.start(patch.object(dependency.urllib.request, 'urlopen',
                                                 side_effect=lambda *a, **k: Response(self.payload)))

    def start(self, patcher):
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_installs_universal_app_and_clipboard_without_developer_tools(self):
        result = dependency.ensure(self.root, self.release)
        self.assertEqual(result['native_gui'], 'installed')
        self.assertTrue((self.root / 'apps' / gui.APP_NAME).is_dir())
        self.assertEqual((self.release / 'build/gui_clipboard_paste').read_bytes(), universal())
        self.assertTrue(all(c[0] in ('/usr/bin/codesign', '/bin/ps') for c in self.commands))
        self.assertEqual(json.loads((self.root / 'data/gui-owned.json').read_text())['installed_by'], str(self.root.resolve()))

    def test_default_reuses_app_and_refreshes_clipboard(self):
        dependency.ensure(self.root, self.release)
        app = self.root / 'apps' / gui.APP_NAME
        binary = app / 'Contents/MacOS' / gui.EXEC_NAME
        binary.write_bytes(b'old signed app')
        result = dependency.ensure(self.root, self.release)
        self.assertEqual(result['native_gui'], 'reused')
        self.assertEqual(binary.read_bytes(), b'old signed app')
        self.assertTrue((self.release / 'build/gui_clipboard_paste').is_file())

    def test_explicit_replacement_keeps_previous_backup(self):
        dependency.ensure(self.root, self.release)
        binary = self.root / 'apps' / gui.APP_NAME / 'Contents/MacOS' / gui.EXEC_NAME
        binary.write_bytes(b'old app')
        result = dependency.ensure(self.root, self.release, replace=True)
        self.assertEqual(result['native_gui'], 'installed')
        self.assertEqual(binary.read_bytes(), universal())
        backups = list((self.root / 'data/backups').glob('gui-previous-*.app'))
        self.assertEqual((backups[0] / 'Contents/MacOS' / gui.EXEC_NAME).read_bytes(), b'old app')

    def test_running_owned_app_stops_exact_user_process_before_replacement(self):
        dependency.ensure(self.root, self.release)
        executable = self.root.resolve() / 'apps' / gui.APP_NAME / 'Contents/MacOS' / gui.EXEC_NAME
        ps_outputs = iter([f'{dependency.os.getuid()} 123 {executable} --serve\n', ''])
        def run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=next(ps_outputs) if argv[0] == '/bin/ps' else '')
        with patch.object(subprocess, 'run', side_effect=run), patch.object(dependency.os, 'kill') as kill:
            dependency.ensure(self.root, self.release, replace=True)
        kill.assert_called_once_with(123, signal.SIGTERM)
        self.assertEqual(self.download.call_count, 2)

    def test_unresponsive_owned_app_fails_before_download(self):
        dependency.ensure(self.root, self.release)
        executable = self.root.resolve() / 'apps' / gui.APP_NAME / 'Contents/MacOS' / gui.EXEC_NAME
        output = f'{dependency.os.getuid()} 123 {executable} --serve\n'
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=output)), patch.object(dependency.os, 'kill') as kill, patch.object(dependency.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'did not exit'):
                dependency.ensure(self.root, self.release, replace=True)
        kill.assert_called_once_with(123, signal.SIGTERM)
        self.assertEqual(self.download.call_count, 1)

    def test_group_writable_owned_app_refused_before_download(self):
        dependency.ensure(self.root, self.release)
        app = self.root / 'apps' / gui.APP_NAME
        app.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'ownership or permissions'):
            dependency.ensure(self.root, self.release)
        self.assertEqual(self.download.call_count, 1)

    def test_unknown_app_refused_before_network(self):
        (self.root / 'apps' / gui.APP_NAME).mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'owner metadata'):
            dependency.ensure(self.root, self.release, replace=True)
        self.download.assert_not_called()

    def test_digest_mismatch_does_not_install(self):
        with patch.object(dependency, 'RELEASE_SHA256', '0' * 64):
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                dependency.ensure(self.root, self.release)
        self.assertFalse((self.root / 'apps' / gui.APP_NAME).exists())
        self.assertFalse((self.release / 'build/gui_clipboard_paste').exists())

    def test_unpublished_pin_fails_without_download(self):
        with patch.object(dependency, 'RELEASE_SHA256', ''):
            with self.assertRaisesRegex(RuntimeError, 'not published'):
                dependency.ensure(self.root, self.release)
        self.download.assert_not_called()

    def test_rejects_traversal_symlinks_duplicates_and_expansion(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('gui_clipboard_paste', tarfile.SYMTYPE),
                           ('gui_clipboard_paste', tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as temporary:
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = '/tmp/target'
                archive = Path(temporary) / 'release.tar.gz'
                archive.write_bytes(archive_bytes(member))
                with self.assertRaises(RuntimeError):
                    dependency.extract_release(archive, Path(temporary) / 'out')
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / 'release.tar.gz'
            archive.write_bytes(gzip.compress(b'x' * 4096))
            with patch.object(dependency, 'MAX_EXPANDED', 1024):
                with self.assertRaisesRegex(RuntimeError, 'decompression'):
                    dependency.extract_release(archive, Path(temporary) / 'out')

    def test_rejects_missing_architecture(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'binary'
            executable.write_bytes(struct.pack('>II', 0xcafebabe, 1) + struct.pack('>IIIII', 0x0100000c, 0, 28, 4, 0) + b'xxxx')
            with self.assertRaisesRegex(RuntimeError, 'universal'):
                dependency.verify_universal(executable)


if __name__ == '__main__':
    unittest.main()
