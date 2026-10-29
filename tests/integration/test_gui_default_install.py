"""GUI provisioning keeps owner-managed app identity across release updates."""
import json
from pathlib import Path
import plistlib
import subprocess
from unittest.mock import patch

import tempfile
import unittest

from scripts import build_mac_control_gui as gui
from scripts import install_mac_control as installer


def managed_app(root, home):
    app = home / "Applications" / gui.APP_NAME
    binary = app / "Contents/MacOS" / gui.EXEC_NAME
    binary.parent.mkdir(parents=True)
    binary.write_text("existing binary")
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": gui.BUNDLE, "CFBundleExecutable": gui.EXEC_NAME}))
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data/gui-owned.json").write_text(json.dumps({
        "app": str(app), "bundle": gui.BUNDLE, "installed_by": str(root)}))
    return app


class GuiInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.patches = []
        class Patcher:
            def setattr(inner, target, name, value):
                mocked = patch.object(target, name, value)
                mocked.start()
                self.addCleanup(mocked.stop)
        self.provision = provision(Path(self.temporary.name), Patcher())

    def test_default_installs_gui_and_clipboard_without_start(self):
        check_default_installs_gui_and_clipboard_without_start(self.provision)

    def test_update_reuses_app_but_provisions_clipboard(self):
        check_update_reuses_app_but_provisions_clipboard(self.provision)

    def test_explicit_rebuild_and_opt_out(self):
        check_explicit_rebuild_and_opt_out(self.provision)

    def test_plan_does_not_provision(self):
        check_plan_does_not_provision(self.provision)

    def test_refuses_unowned(self):
        unknown_or_damaged_app_refused(self.provision, "unowned")

    def test_refuses_metadata(self):
        unknown_or_damaged_app_refused(self.provision, "metadata")

    def test_refuses_symlink(self):
        unknown_or_damaged_app_refused(self.provision, "symlink")

    def test_refuses_signature(self):
        unknown_or_damaged_app_refused(self.provision, "signature")

    def test_cli_install_and_update_preserve_auto_mode(self):
        root, _, _ = self.provision
        for action in ("--install", "--update"):
            for flag, expected in ((None, None), ("--with-gui", True), ("--without-gui", False)):
                argv = ["installer", action, "--without-chatbridge", "--root", str(root)]
                if flag:
                    argv.append(flag)
                with patch.object(installer.sys, "argv", argv), patch.object(installer, "install", return_value={}) as install:
                    self.assertEqual(installer.main(), 0)
                self.assertIs(install.call_args.args[2], expected)

    def test_direct_builder_refuses_unknown_app_before_build(self):
        root, home, _ = self.provision
        managed_app(root, home)
        (root / "data/gui-owned.json").unlink()
        with patch.object(gui.sys, "argv", ["builder", "--root", str(root), "--install"]), patch.object(gui, "build") as build:
            with self.assertRaises(RuntimeError):
                gui.main()
            build.assert_not_called()

    def test_refuses_symlink_ownership_record(self):
        root, home, _ = self.provision
        managed_app(root, home)
        record = root / "data/gui-owned.json"
        saved = record.with_suffix(".saved")
        record.rename(saved)
        record.symlink_to(saved)
        with self.assertRaises(RuntimeError):
            gui.verify_owned(root)

    def test_refuses_foreign_owner_metadata(self):
        root, home, _ = self.provision
        managed_app(root, home)
        record = root / "data/gui-owned.json"
        metadata = json.loads(record.read_text())
        metadata["installed_by"] = "/other/installation"
        record.write_text(json.dumps(metadata))
        with self.assertRaises(RuntimeError):
            gui.verify_owned(root)

    def test_skip_preserves_enabled_gui_clipboard_in_new_release(self):
        root, home, commands = self.provision
        app = managed_app(root, home)
        (root / "data/feature_flags.json").write_text('{"native_gui": true}')
        with patch.object(installer, "source_id", return_value="next-release"):
            result = installer.install(root, with_chatbridge=False, with_gui=False)
        self.assertEqual(result["native_gui"], "reused")
        self.assertTrue(app.exists())
        self.assertTrue(json.loads((root / "data/feature_flags.json").read_text())["native_gui"])
        clipboard = [c for c in commands if "build_dev_clipboard.py" in " ".join(c)]
        self.assertEqual(len(clipboard), 1)
        self.assertIn("next-release", clipboard[0][1])
        self.assertFalse(any("build_mac_control_gui.py" in " ".join(c) for c in commands))

    def test_missing_clt_gives_manual_install_instruction(self):
        with patch.object(gui.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "xcrun")) as run:
            with self.assertRaisesRegex(RuntimeError, "xcode-select --install"):
                gui.require_build_tools()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/xcrun", "--find", "swiftc"])


def provision(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "root"
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(installer.sys, "platform", "darwin")
    monkeypatch.setattr(installer, "source_id", lambda: "test-release")
    monkeypatch.setattr(installer, "find_uv", lambda: "/fake/uv")
    monkeypatch.setattr(installer, "smoke", lambda *args: None)
    def copy(dest):
        (dest / "bin").mkdir()
        (dest / "bin/mac-control-stdio-mcp.sh").touch()
    monkeypatch.setattr(installer, "copy_source", copy)
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(installer, "run", run)
    monkeypatch.setattr(gui.subprocess, "run", run)
    return root, home, commands


def check_default_installs_gui_and_clipboard_without_start(provision):
    root, home, commands = provision
    installer.install(root, with_chatbridge=False)
    assert any("build_mac_control_gui.py" in " ".join(c) for c in commands)
    assert any("build_dev_clipboard.py" in " ".join(c) for c in commands)
    assert not any(c[0] in ("open", "/usr/bin/open", "launchctl") for c in commands)


def check_update_reuses_app_but_provisions_clipboard(provision):
    root, home, commands = provision
    app = managed_app(root, home)
    before = (app / "Contents/MacOS" / gui.EXEC_NAME).read_bytes()
    result = installer.install(root, with_chatbridge=False)
    assert result["native_gui"] == "reused"
    assert (app / "Contents/MacOS" / gui.EXEC_NAME).read_bytes() == before
    assert not any("build_mac_control_gui.py" in " ".join(c) for c in commands)
    assert any("build_dev_clipboard.py" in " ".join(c) for c in commands)
    assert any(c[0] == "/usr/bin/codesign" for c in commands)


def check_explicit_rebuild_and_opt_out(provision):
    root, home, commands = provision
    managed_app(root, home)
    installer.install(root, with_chatbridge=False, with_gui=True)
    assert any("build_mac_control_gui.py" in " ".join(c) for c in commands)
    commands.clear()
    installer.install(root, with_chatbridge=False, with_gui=False)
    assert not any("build_mac_control_gui.py" in " ".join(c) for c in commands)
    assert any("build_dev_clipboard.py" in " ".join(c) for c in commands)


def unknown_or_damaged_app_refused(provision, damage):
    root, home, commands = provision
    app = managed_app(root, home)
    if damage == "unowned":
        (root / "data/gui-owned.json").unlink()
    elif damage == "metadata":
        (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "other"}))
    elif damage == "symlink":
        (app / "Contents/link").symlink_to("/tmp")
    with patch.object(gui.subprocess, "run", side_effect=(
            subprocess.CalledProcessError(1, "codesign") if damage == "signature" else None)):
        with unittest.TestCase().assertRaises((RuntimeError, subprocess.CalledProcessError)):
            installer.install(root, with_chatbridge=False, with_gui=True)
    assert app.exists()


def check_plan_does_not_provision(provision):
    from contextlib import redirect_stdout
    from io import StringIO
    root, home, commands = provision
    output = StringIO()
    with patch.object(installer.sys, "argv", ["installer", "--plan", "--root", str(root)]), redirect_stdout(output):
        assert installer.main() == 0
    assert json.loads(output.getvalue())["native_background_gui"] == "install_if_missing_reuse_owned"
    assert not commands and not root.exists()
