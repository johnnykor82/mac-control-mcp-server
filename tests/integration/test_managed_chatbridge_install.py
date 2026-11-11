"""The single Mac Control installer provisions and owns its ChatBridge dependency."""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import install_mac_control as installer
from scripts import setup_chatbridge_dependency as cb


class ManagedChatBridgeTests(unittest.TestCase):
    def test_chatbridge_installer_targets_mac_control_deps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "deps/chatbridge-source"
            for name in ("install.sh", "LICENSE", "pyproject.toml", "scripts/installer.py"):
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('name = "chatbridge-gateway"\n')
            with patch.object(cb, "assert_installable"), \
                 patch.object(cb, "verify_managed_install"), \
                 patch.object(cb, "verify", return_value={"status": "compatible"}), \
                 patch.object(cb.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner:
                cb.install(source, install_root=root)
            args = runner.call_args.args[0]
            self.assertEqual(args[args.index("--prefix") + 1], str(root.resolve() / "deps/chatbridge"))
            self.assertEqual(args[args.index("--state-dir") + 1], str(root.resolve() / "deps/chatbridge-data"))
            self.assertEqual(args[args.index("--port") + 1], "8787")
            self.assertEqual(args[args.index("--label") + 1], cb.MANAGED_LABEL)

    def test_existing_service_must_be_owned_within_same_root(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            home.mkdir()
            root = home / "MacControlMCP"
            prefix = root / "deps/chatbridge"
            state = root / "deps/chatbridge-data"
            plist = home / ("Library/LaunchAgents/" + cb.MANAGED_LABEL + ".plist")
            plist.parent.mkdir(parents=True)
            config = {"Label": cb.MANAGED_LABEL, "ChatBridgeInstaller": "1",
                      "WorkingDirectory": str(prefix / "releases/installed"),
                      "EnvironmentVariables": {"CHATBRIDGE_DB": str(state / "state.db")}}
            with patch.object(cb.Path, "home", return_value=home):
                plist.write_bytes(plistlib.dumps(config))
                cb.verify_managed_install(root)
                config["WorkingDirectory"] = str(home / ".local/share/chatbridge/releases/installed")
                plist.write_bytes(plistlib.dumps(config))
                with self.assertRaisesRegex(RuntimeError, "outside"):
                    cb.verify_managed_install(root)

    def test_compatible_external_endpoint_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(cb, "verify", return_value={"status": "compatible"}), \
                 patch.object(cb, "verify_managed_install", side_effect=RuntimeError("external")):
                with self.assertRaisesRegex(RuntimeError, "external"):
                    cb.ensure(install_root=Path(directory))

    def test_default_install_passes_root_to_dependency_manager(self):
        with patch.object(installer, "paths", return_value={}), \
             patch.object(installer.sys, "platform", "darwin"), \
             patch.object(cb, "ensure") as ensure, \
             patch.object(installer, "find_uv", side_effect=RuntimeError("stop-after-dependency")):
            with self.assertRaisesRegex(RuntimeError, "stop-after-dependency"):
                installer.install(Path("unused"))
        ensure.assert_called_once_with(cb.DEFAULT_URL, None, install_root=Path("unused").resolve())

    def test_existing_managed_source_is_upgraded_before_maccontrol_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'data').mkdir()
            (root / 'data/chatbridge_connection.txt').write_text(cb.DEFAULT_URL)
            (root / 'deps/chatbridge-source').mkdir(parents=True)
            with patch.object(installer, 'paths', return_value={
                    'data': root / 'data', 'root': root, 'release': root / 'releases/new',
                    'current': root / 'current', 'releases': root / 'releases'}), \
                 patch.object(installer.sys, 'platform', 'darwin'), \
                 patch.object(cb, 'ensure', return_value={
                     'url': cb.DEFAULT_URL, 'status': 'compatible'}), \
                 patch.object(cb, 'upgrade_managed',
                              return_value={'status':'upgraded'}) as upgrade, \
                 patch.object(cb, 'browser_login_status', return_value={
                     'authenticated': True, 'status': 'ready'}), \
                 patch.object(installer, 'find_uv',
                              side_effect=RuntimeError('stop-before-activation')):
                with self.assertRaisesRegex(RuntimeError, 'stop-before-activation'):
                    installer.install(root, with_chatbridge=True)
            upgrade.assert_called_once_with(root.resolve(), url=cb.DEFAULT_URL)

    def test_pinned_release_persisted_under_managed_root(self):
        import tarfile
        from tests.integration.test_chatbridge_bootstrap import archive_bytes
        payload = archive_bytes()
        class Response(io.BytesIO):
            def geturl(self): return cb.RELEASE_URL
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MacControlMCP"
            root.mkdir()
            with patch.object(cb, "assert_installable"), \
                 patch.object(cb, "RELEASE_SHA256", hashlib.sha256(payload).hexdigest()), \
                 patch.object(cb.urllib.request, "urlopen", return_value=Response(payload)), \
                 patch.object(cb, "install", return_value={"status": "compatible"}) as run:
                cb.install_pinned(install_root=root)
            saved, _, _ = cb.managed_paths(root)
            self.assertTrue((saved / "scripts/installer.py").is_file())
            self.assertEqual(run.call_args.args[0], saved)

    def test_purge_invokes_chatbridge_own_uninstaller_with_owned_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / "MacControlMCP"
            src, prefix, state = cb.managed_paths(root)
            script = src / "scripts/installer.py"
            script.parent.mkdir(parents=True)
            script.write_text("safe test source")
            plist = home / ("Library/LaunchAgents/" + cb.MANAGED_LABEL + ".plist")
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({
                "Label": cb.MANAGED_LABEL,
                "ChatBridgeInstaller": "1",
                "WorkingDirectory": str(prefix / "releases/build"),
                "EnvironmentVariables": {"CHATBRIDGE_DB": str(state / "state.db")}}))
            with patch.object(Path, "home", return_value=home), \
                 patch.object(installer.subprocess, "run",
                              return_value=SimpleNamespace(returncode=0)) as runner:
                self.assertTrue(installer._remove_managed_chatbridge(root))
            args = runner.call_args.args[0]
            for flag in ("uninstall", "--remove-app", "--purge-data", "--yes"):
                self.assertIn(flag, args)
            self.assertEqual(args[args.index("--prefix")+1], str(prefix))
            self.assertEqual(args[args.index("--state-dir")+1], str(state))

    def test_foreign_chatbridge_is_never_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / "MacControlMCP"
            src, prefix, state = cb.managed_paths(root)
            script = src / "scripts/installer.py"
            script.parent.mkdir(parents=True)
            script.write_text("safe test source")
            plist = home / "Library/LaunchAgents/net.chatbridge.gateway.plist"
            plist.parent.mkdir(parents=True)
            plist.write_bytes(plistlib.dumps({
                "Label": "net.chatbridge.gateway", "ChatBridgeInstaller": "1",
                "WorkingDirectory": str(home / ".local/share/chatbridge/releases/build"),
                "EnvironmentVariables": {"CHATBRIDGE_DB": str(home / ".chatbridge/state.db")}}))
            with patch.object(Path, "home", return_value=home), \
                 patch.object(installer.subprocess, "run") as runner:
                self.assertFalse(installer._remove_managed_chatbridge(root))
                runner.assert_not_called()

    def test_purge_uninstalls_owned_dependency_before_deleting_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MacControlMCP"
            root.mkdir()
            (root / ".mac-control-installer-owned").write_text("owned")
            (root / "releases").mkdir()
            (root / "data/workspace").mkdir(parents=True)
            (root / "data/workspace/file").write_text("secret")
            with patch.object(installer, "DEFAULT_ROOT", root), \
                 patch.object(installer, "_remove_managed_chatbridge", return_value=True) as uninstall_cb:
                with self.assertRaisesRegex(RuntimeError, "Legacy user workspace"):
                    installer.purge(root)
            self.assertTrue(root.exists())
            self.assertEqual((root / "data/workspace/file").read_text(), "secret")
            uninstall_cb.assert_not_called()

    def test_full_purge_stops_before_deleting_if_public_route_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "MacControlMCP"
            root.mkdir()
            (root / ".mac-control-installer-owned").write_text("owned")
            with patch.object(installer, "DEFAULT_ROOT", root), \
                 patch("scripts.setup_network.assert_public_route_safe_for_uninstall",
                       side_effect=RuntimeError("active Funnel")), \
                 patch.object(installer, "_remove_managed_chatbridge") as uninstall_cb:
                with self.assertRaisesRegex(RuntimeError, "active Funnel"):
                    installer.purge(root)
                uninstall_cb.assert_not_called()
                self.assertTrue((root / ".mac-control-installer-owned").is_file())




class AdoptedLegacyChatBridgeLabelTests(unittest.TestCase):
    def fixture(self, directory, *, marker='1', profile=True, release=True, dual=False):
        home = Path(directory).resolve() / 'home'
        root = home / 'MacControlMCP'
        agents = home / 'Library/LaunchAgents'
        agents.mkdir(parents=True)
        _, prefix, state = cb.managed_paths(root)
        version = prefix / 'releases/old'
        version.mkdir(parents=True)
        path = agents / 'net.chatbridge.gateway.plist'
        env = {'CHATBRIDGE_DB': str(state / 'state.db'),
               'CHATBRIDGE_CHROME_PROFILE': str(state / 'chrome-profile'),
               'CHATBRIDGE_PORT': '8787'}
        if not profile:
            env['CHATBRIDGE_CHROME_PROFILE'] = str(home / '.chatbridge/chrome-profile')
        data = {'Label': 'net.chatbridge.gateway', 'ChatBridgeInstaller': marker,
                'WorkingDirectory': str(version if release else home / '.other/release'),
                'ProgramArguments': [str(version / '.venv/bin/python'), '-m', 'chatbridge'],
                'EnvironmentVariables': env}
        path.write_bytes(plistlib.dumps(data))
        path.chmod(0o600)
        if dual:
            other = agents / (cb.MANAGED_LABEL + '.plist')
            other.write_bytes(plistlib.dumps({**data, 'Label': cb.MANAGED_LABEL}))
        output = (f'path = {path}\nprogram = {version}/.venv/bin/python\n'
                  'state = running\npid = 14119\n')
        launch = SimpleNamespace(returncode=0, stdout=output, stderr='')
        return home, root, path, launch

    def test_adopt_owner_managed_running_original_label_and_port(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, path, launch = self.fixture(directory)
            with patch.object(cb.Path, 'home', return_value=home), \
                 patch.object(cb.subprocess, 'run', return_value=launch):
                self.assertEqual(cb.managed_service_label(root), 'net.chatbridge.gateway')
                self.assertEqual(cb.owned_endpoint(root), 'http://127.0.0.1:8787')
                cb.verify_managed_install(root)
            self.assertTrue(path.exists())
            self.assertFalse((path.parent / (cb.MANAGED_LABEL + '.plist')).exists())

    def test_never_adopt_foreign_marker_profile_or_release(self):
        for kwargs in ({'marker': 'foreign'}, {'profile': False}, {'release': False}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                home, root, path, launch = self.fixture(directory, **kwargs)
                with patch.object(cb.Path, 'home', return_value=home), \
                     patch.object(cb.subprocess, 'run', return_value=launch):
                    with self.assertRaisesRegex(RuntimeError, 'owned|ownership|outside|foreign'):
                        cb.managed_service_label(root)
                self.assertTrue(path.exists())

    def test_never_adopt_when_both_plists_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, path, launch = self.fixture(directory, dual=True)
            with patch.object(cb.Path, 'home', return_value=home), \
                 patch.object(cb.subprocess, 'run', return_value=launch):
                self.assertEqual(cb.managed_service_label(root), cb.MANAGED_LABEL)

    def test_upgrade_uses_adopted_label_not_second_service(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, path, launch = self.fixture(directory)
            source = root / 'deps/chatbridge-source'
            source.mkdir(parents=True)
            (source / 'pyproject.toml').write_text('version = "0.2.0b11"\n')
            with patch.object(cb.Path, 'home', return_value=home), \
                 patch.object(cb.subprocess, 'run', return_value=launch), \
                 patch.object(cb, 'assert_managed_idle'), \
                 patch.object(cb, 'managed_installed_runtime_version', return_value='0.2.0b11'), \
                 patch.object(cb, 'latest_published_release', return_value={'version':'0.2.0b12','version_number':12}), \
                 patch.object(cb, 'download_latest_source') as download:
                with tempfile.TemporaryDirectory() as source_dir:
                    package = Path(source_dir) / 'package'
                    package.mkdir()
                    (package / 'pyproject.toml').write_text('version = "0.2.0b12"\n')
                    (package / 'scripts').mkdir()
                    (package / 'scripts/installer.py').write_text('test')
                    download.return_value = package
                    with patch.object(cb, 'verify', return_value={'status':'compatible'}):
                        cb.upgrade_managed(root)
            self.assertTrue(path.exists())
            self.assertFalse((path.parent / (cb.MANAGED_LABEL + '.plist')).exists())


class StaleManagedAliasQuarantineTests(unittest.TestCase):
    def fixture(self, directory, *, shared=True, owner=True, valid_root=True):
        home = Path(directory) / "home"
        root = home / "MacControlMCP"
        prefix = root / "deps/chatbridge"
        state = root / "deps/chatbridge-data"
        release = prefix / "releases/v1"
        release.mkdir(parents=True)
        state.mkdir(parents=True)
        agents = home / "Library/LaunchAgents"
        agents.mkdir(parents=True)
        managed = agents / (cb.MANAGED_LABEL + ".plist")
        legacy = agents / "net.chatbridge.gateway.plist"
        env = {"CHATBRIDGE_DB": str(state / "state.db"),
               "CHATBRIDGE_CHROME_PROFILE": str(state / "chrome-profile"),
               "CHATBRIDGE_PORT": "8787"}
        base = {"ChatBridgeInstaller": "1", "WorkingDirectory": str(release),
                "EnvironmentVariables": env}
        managed.write_bytes(plistlib.dumps({**base, "Label": cb.MANAGED_LABEL}))
        legacy_config = {**base, "Label": "net.chatbridge.gateway"}
        if not owner:
            legacy_config.pop("ChatBridgeInstaller")
        if not shared:
            legacy_config["EnvironmentVariables"] = {
                **env, "CHATBRIDGE_DB": str(home / ".chatbridge/state.db"),
                "CHATBRIDGE_CHROME_PROFILE": str(home / ".chatbridge/chrome-profile")}
        if not valid_root:
            legacy_config["WorkingDirectory"] = str(home / ".local/share/chatbridge/releases/v1")
        payload = plistlib.dumps(legacy_config)
        legacy.write_bytes(payload)
        return home, root, legacy, payload

    def test_verified_inactive_duplicate_quarantined_with_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            absent = SimpleNamespace(returncode=113, stderr=(
                f'Could not find service "net.chatbridge.gateway" in domain for user gui: {os.getuid()}'), stdout="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=absent) as status:
                with cb.quarantine_stale_alias(root):
                    self.assertFalse(legacy.exists())
                self.assertFalse(legacy.exists())
            self.assertGreaterEqual(status.call_count, 2)
            saved = list((root / "deps/chatbridge-data/installer-backups/alias-quarantine").glob("*.plist"))
            self.assertGreaterEqual(len(saved), 2)
            self.assertTrue(all(item.read_bytes() == payload for item in saved))

    def test_failed_update_restores_exact_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            absent = SimpleNamespace(returncode=113, stderr=(
                f'Could not find service "net.chatbridge.gateway" in domain for user gui: {os.getuid()}'), stdout="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=absent):
                with self.assertRaisesRegex(RuntimeError, "installer failed"):
                    with cb.quarantine_stale_alias(root):
                        self.assertFalse(legacy.exists())
                        raise RuntimeError("installer failed")
            self.assertEqual(legacy.read_bytes(), payload)

    def test_becomes_active_between_checks_is_never_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            absent = SimpleNamespace(returncode=113, stderr=(
                f'Could not find service "net.chatbridge.gateway" in domain for user gui: {os.getuid()}'), stdout="")
            active = SimpleNamespace(returncode=0, stdout="state = running", stderr="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", side_effect=[absent, active]) as run:
                with self.assertRaisesRegex(RuntimeError, "loaded"):
                    with cb.quarantine_stale_alias(root):
                        self.fail("Must not change plist after service activates")
            self.assertEqual(legacy.read_bytes(), payload)
            self.assertEqual(run.call_count, 2)

    def test_failed_dependency_ensure_restores_duplicate_in_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            (root / 'data').mkdir()
            absent = SimpleNamespace(returncode=113, stderr=(
                f'Could not find service "net.chatbridge.gateway" in domain for user gui: {os.getuid()}'), stdout="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=absent), \
                 patch.object(installer.sys, 'platform', 'darwin'), \
                 patch.object(cb, 'ensure', side_effect=RuntimeError('dependency failed')):
                with self.assertRaisesRegex(RuntimeError, 'dependency failed'):
                    installer.install(root, with_chatbridge=True)
            self.assertEqual(legacy.read_bytes(), payload)

    def test_successful_ensure_and_upgrade_leave_alias_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            (root / 'data').mkdir()
            (root / 'deps/chatbridge-source').mkdir()
            absent = SimpleNamespace(returncode=113, stderr=(
                f'Could not find service "net.chatbridge.gateway" in domain for user gui: {os.getuid()}'), stdout="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=absent), \
                 patch.object(installer.sys, 'platform', 'darwin'), \
                 patch.object(cb, 'ensure', return_value={'url': cb.DEFAULT_URL}), \
                 patch.object(cb, 'upgrade_managed', return_value={'status': 'upgraded'}) as upgrade, \
                 patch.object(cb, 'browser_login_status', return_value={'authenticated': True}), \
                 patch.object(installer, 'find_uv', side_effect=RuntimeError('later stage')):
                with self.assertRaisesRegex(RuntimeError, 'later stage'):
                    installer.install(root, with_chatbridge=True)
            self.assertFalse(legacy.exists())
            upgrade.assert_called_once_with(root.resolve(), url=cb.DEFAULT_URL)
            retained = list((root / 'deps/chatbridge-data/installer-backups/alias-quarantine').glob('*.plist'))
            self.assertEqual(len(retained), 2)
            self.assertTrue(all(x.read_bytes() == payload for x in retained))

    def test_backup_symlink_is_rejected_before_quarantine(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            unsafe = root / 'deps/chatbridge-data/installer-backups'
            unsafe.symlink_to(home, target_is_directory=True)
            absent = SimpleNamespace(returncode=113, stderr=(
                f'Could not find service "net.chatbridge.gateway" in domain for user gui: {os.getuid()}'), stdout="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=absent):
                with self.assertRaisesRegex(RuntimeError, 'backup'):
                    with cb.quarantine_stale_alias(root):
                        self.fail('Unsafe backup root must be rejected')
            self.assertEqual(legacy.read_bytes(), payload)

    def test_active_duplicate_is_never_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            active = SimpleNamespace(returncode=0, stdout="state = running", stderr="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=active):
                with self.assertRaisesRegex(RuntimeError, "active|loaded"):
                    with cb.quarantine_stale_alias(root):
                        self.fail("Must refuse active duplicate")
            self.assertEqual(legacy.read_bytes(), payload)

    def test_unknown_launchctl_failure_is_not_interpreted_as_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory)
            ambiguous = SimpleNamespace(returncode=1, stderr="launchd unavailable", stdout="")
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run", return_value=ambiguous):
                with self.assertRaisesRegex(RuntimeError, "confirm|inactive"):
                    with cb.quarantine_stale_alias(root):
                        self.fail("Must refuse uncertain status")
            self.assertEqual(legacy.read_bytes(), payload)

    def test_foreign_owner_or_release_root_is_never_moved(self):
        for kwargs in ({"owner": False}, {"valid_root": False}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                home, root, legacy, payload = self.fixture(directory, **kwargs)
                with patch.object(cb.Path, "home", return_value=home), \
                     patch.object(cb.subprocess, "run") as status:
                    with self.assertRaisesRegex(RuntimeError, "owner|foreign|outside"):
                        with cb.quarantine_stale_alias(root):
                            self.fail("Must not quarantine foreign service")
                    status.assert_not_called()
                self.assertEqual(legacy.read_bytes(), payload)

    def test_independent_legacy_service_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            home, root, legacy, payload = self.fixture(directory, shared=False)
            with patch.object(cb.Path, "home", return_value=home), \
                 patch.object(cb.subprocess, "run") as status:
                with cb.quarantine_stale_alias(root):
                    pass
                status.assert_not_called()
            self.assertEqual(legacy.read_bytes(), payload)



class ManagedChatBridgeUpgradeTests(unittest.TestCase):
    def make_source(self, root, version):
        source = root / 'deps/chatbridge-source'
        (source / 'scripts').mkdir(parents=True, exist_ok=True)
        (source / 'scripts/installer.py').write_text('import sys\n')
        (source / 'pyproject.toml').write_text(
            'name = "chatbridge-gateway"\nversion = "' + version + '"\n')
        return source

    def test_upgrades_owned_source_using_pinned_archive_preserving_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = self.make_source(root, '0.2.0b11')
            pinned = root / 'pinned'
            (pinned / 'scripts').mkdir(parents=True)
            (pinned / 'scripts/installer.py').write_text('import sys\n')
            (pinned / 'pyproject.toml').write_text(
                'name = "chatbridge-gateway"\nversion = "0.2.0b12"\n')
            with patch.object(cb, 'verify_managed_install'), \
                 patch.object(cb, 'managed_service_label', return_value=cb.MANAGED_LABEL), \
                 patch.object(cb, 'assert_managed_idle'), \
                 patch.object(cb, 'latest_published_release', return_value={'version':'0.2.0b12','version_number':12}), \
                 patch.object(cb, 'download_latest_source', return_value=pinned), \
                 patch.object(cb.subprocess, 'run',
                              return_value=SimpleNamespace(returncode=0)) as runner, \
                 patch.object(cb, 'verify', return_value={'status':'compatible'}):
                result = cb.upgrade_managed(root, url=cb.DEFAULT_URL)
            self.assertEqual(result['status'], 'upgraded')
            self.assertIn('0.2.0b12', (old / 'pyproject.toml').read_text())
            self.assertIn('upgrade', runner.call_args.args[0])
            self.assertIn(cb.MANAGED_LABEL, runner.call_args.args[0])
            backups = list((root / 'deps').glob('chatbridge-source.previous-*'))
            self.assertEqual(len(backups), 1)
            self.assertIn('0.2.0b11', (backups[0] / 'pyproject.toml').read_text())

    def test_busy_chatbridge_is_not_interrupted_by_dependency_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_source(root, '0.2.0b11')
            with patch.object(cb, 'verify_managed_install'), \
                 patch.object(cb, 'latest_published_release', return_value={'version':'0.2.0b12','version_number':12}), \
                 patch.object(cb, 'download_latest_source') as download, \
                 patch.object(cb.subprocess, 'run') as runner, \
                 patch.object(cb.urllib.request, 'urlopen', return_value=io.BytesIO(
                    b'{"active":2,"browser":{"active_requests":1}}')):
                with self.assertRaisesRegex(RuntimeError, 'active'):
                    cb.upgrade_managed(root, url=cb.DEFAULT_URL)
            download.assert_not_called()
            runner.assert_not_called()

    def test_matching_managed_source_skips_download_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_source(root, '0.2.0b12')
            with patch.object(cb, 'verify_managed_install'), \
                 patch.object(cb, 'latest_published_release', return_value={'version':'0.2.0b12','version_number':12}), \
                 patch.object(cb, 'download_latest_source') as download, \
                 patch.object(cb.subprocess, 'run') as runner:
                result = cb.upgrade_managed(root, url=cb.DEFAULT_URL)
            self.assertEqual(result['status'], 'current')
            download.assert_not_called()
            runner.assert_not_called()

    def test_foreign_managed_service_is_never_touched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_source(root, '0.2.0b11')
            with patch.object(cb, 'verify_managed_install',
                              side_effect=PermissionError('foreign')), \
                 patch.object(cb, 'download_pinned_source') as download, \
                 patch.object(cb.subprocess, 'run') as runner:
                with self.assertRaises(PermissionError):
                    cb.upgrade_managed(root, url=cb.DEFAULT_URL)
            download.assert_not_called()
            runner.assert_not_called()

    def test_failed_upgrade_preserves_owned_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.make_source(root, '0.2.0b11')
            pinned = root / 'pinned'
            (pinned / 'scripts').mkdir(parents=True)
            (pinned / 'scripts/installer.py').write_text('import sys\n')
            (pinned / 'pyproject.toml').write_text(
                'name = "chatbridge-gateway"\nversion = "0.2.0b12"\n')
            with patch.object(cb, 'verify_managed_install'), \
                 patch.object(cb, 'managed_service_label', return_value=cb.MANAGED_LABEL), \
                 patch.object(cb, 'assert_managed_idle'), \
                 patch.object(cb, 'latest_published_release',
                              return_value={'version': '0.2.0b12', 'version_number': 12}), \
                 patch.object(cb, 'download_latest_source', return_value=pinned), \
                 patch.object(cb.urllib.request, 'urlopen',
                              side_effect=AssertionError('No network in upgrade fixture')), \
                 patch.object(cb.subprocess, 'run',
                              return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(RuntimeError):
                    cb.upgrade_managed(root, url=cb.DEFAULT_URL)
            self.assertIn('0.2.0b11', (source / 'pyproject.toml').read_text())


if __name__ == "__main__":
    unittest.main()
