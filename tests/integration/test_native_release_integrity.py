"""FR-020: native AX must stay in one signed GUI .app and owner-only IPC."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import install_mac_control, build_mac_control_gui
from mac_control import background_native_ops as native

class NativeReleaseIntegrity(unittest.TestCase):
    def test_native_ax_source_is_in_installer_manifest(self):
        files={p.relative_to(install_mac_control.SOURCE).as_posix()
               for p in install_mac_control.install_sources()}
        self.assertIn('scripts/dev_gui_native_background.swift.part',files)
        self.assertIn('scripts/build_mac_control_gui.py',files)
        self.assertIn('src/mac_control/background_native_ops.py',files)
        self.assertNotIn('scripts/dev_native_background.swift',files)
        self.assertNotIn('scripts/build_dev_native.py',files)

    def test_native_uses_gui_ipc_no_separate_child_process(self):
        with patch('mac_control.legacy_handlers.gui_ops._call',return_value={'apps':[]}) as call:
            response=native.helper('apps')
        self.assertEqual(response,{'ok':True,'result':{'apps':[]}})
        call.assert_called_once_with('native_backend',timeout=20,native_op='apps')

    def test_native_missing_gui_returns_structured_error(self):
        with patch('mac_control.legacy_handlers.gui_ops._call',side_effect=RuntimeError('ACCESSIBILITY_DENIED: grant required')):
            response=native.helper('windows',bundle_id='com.example.app')
        self.assertEqual(response['error']['code'],'ACCESSIBILITY_DENIED')

    def test_unsupported_operation_never_reaches_helper(self):
        with patch('mac_control.legacy_handlers.gui_ops._call') as call:
            response=native.helper('arbitrary')
        self.assertEqual(response['error']['code'],'UNKNOWN_ACTION')
        call.assert_not_called()

    def test_gui_build_template_has_native_registration(self):
        text=build_mac_control_gui.NATIVE.read_text()
        self.assertEqual(text.count('func nativeTask('),1)
        self.assertIn('func nativeRequireNonSecure(',text)
        self.assertIn('nativeTask(nativeRequest)',Path('scripts/build_mac_control_gui.py').read_text())

    def test_opt_in_remains_disabled_without_true_flag(self):
        with tempfile.TemporaryDirectory() as folder:
            flag=Path(folder)/'flag.json'
            flag.write_text(json.dumps({'background_native':False}))
            with patch.object(native,'FLAG',flag):self.assertFalse(native.enabled())
            flag.write_text(json.dumps({'background_native':True}))
            with patch.object(native,'FLAG',flag):self.assertTrue(native.enabled())

if __name__=='__main__':unittest.main()
