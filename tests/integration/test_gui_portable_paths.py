"""Portable GUI runtime paths without launching a UI or touching installed apps."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import build_mac_control_gui as gui


class PortableGUIBuildTests(unittest.TestCase):
    def test_build_does_not_embed_the_installing_users_paths(self):
        with tempfile.TemporaryDirectory(prefix="gui-build-") as directory:
            output = Path(directory)

            def compile_fixture(argv, **_kwargs):
                if argv[0] == "/usr/bin/swiftc":
                    Path(argv[argv.index("-o") + 1]).write_bytes(b"fixture")
                return mock.Mock(returncode=0)

            with mock.patch.object(gui, "ROOT", output), \
                 mock.patch.object(gui, "require_build_tools"), \
                 mock.patch.object(gui.subprocess, "run", side_effect=compile_fixture):
                gui.build(Path('/tmp/first-user/quote"root'))
                first = (output / "build/gui_mac_control_generated.swift").read_text()
                gui.build(Path("/tmp/second-user/custom-root"))
                second = (output / "build/gui_mac_control_generated.swift").read_text()
            self.assertEqual(first, second)
            self.assertNotIn("/tmp/first-user", first)
            self.assertNotIn("__MAC_CONTROL_", first)
            self.assertIn("GUIRuntimePaths", first)


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("swiftc"),
                     "macOS Swift compiler required for native runtime checks")
class PortableGUIRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="gui-path-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        source = gui.TEMPLATE.read_text()
        resolver = source[source.index("enum AgentError:"):source.index("\nfunc argument(")]
        permission_cases = source[source.index('    case "request_accessibility":'):
                                  source.index('    case "displays":')]
        permission_stubs = r'''
var permissionCalls: [String] = []
func AXIsProcessTrustedWithOptions(_ options: CFDictionary) -> Bool {
    permissionCalls.append("accessibility")
    return false
}
func CGRequestScreenCaptureAccess() -> Bool {
    permissionCalls.append("screen_capture")
    return false
}
func requestPermission(_ operation: String) -> [String: Any] {
    switch operation {
''' + permission_cases + '\n    default: return [:]\n    }\n}\n'
        harness = r'''
let input = try JSONSerialization.jsonObject(with: Data(CommandLine.arguments[1].utf8)) as! [String: Any]
do {
    if let permission = input["permission"] as? String {
        _ = requestPermission(permission)
        print(String(data: try JSONSerialization.data(withJSONObject: permissionCalls), encoding: .utf8)!)
        exit(0)
    }
    let paths = try GUIRuntimePaths.resolve(arguments: input["arguments"] as! [String],
        environment: input["environment"] as! [String: String], home: input["home"] as! String)
    let output = try JSONSerialization.data(withJSONObject: ["data": paths.dataRoot,
        "socket": paths.socket, "captures": paths.capturePrefix])
    print(String(data: output, encoding: .utf8)!)
} catch {
    print("REJECTED")
}
'''
        swift = Path(cls.temporary.name) / "resolver.swift"
        cls.executable = Path(cls.temporary.name) / "resolver"
        swift.write_text("import Foundation\nimport ApplicationServices\n" + resolver + permission_stubs + harness)
        subprocess.run([shutil.which("swiftc"), "-module-cache-path", str(Path(cls.temporary.name) / "cache"),
                        str(swift), "-o", str(cls.executable)],
                       check=True, capture_output=True, text=True, timeout=60)

    def resolve(self, *, arguments=None, environment=None, home="/Users/new-owner"):
        request = {"arguments": arguments or ["helper"], "environment": environment or {}, "home": home}
        output = subprocess.run([str(self.executable), json.dumps(request)], check=True,
                                capture_output=True, text=True, timeout=5).stdout.strip()
        return output if output == "REJECTED" else json.loads(output)

    def test_permission_requests_are_independent_and_compatibility_is_preserved(self):
        for operation, expected in (("request_accessibility", ["accessibility"]),
                                    ("request_screen_capture", ["screen_capture"]),
                                    ("request_permissions", ["accessibility", "screen_capture"])):
            with self.subTest(operation=operation):
                output = subprocess.run([str(self.executable), json.dumps({"permission": operation})],
                                        check=True, capture_output=True, text=True, timeout=5)
                self.assertEqual(json.loads(output.stdout), expected)

    def test_default_uses_the_current_users_home(self):
        result = self.resolve()
        root = "/Users/new-owner/MacControlMCP/data"
        self.assertEqual(result, {"data": root, "socket": root + "/run/maccontrol-gui.sock",
                                  "captures": root + "/run/gui-captures/"})

    def test_custom_launch_argument_takes_precedence_over_environment(self):
        root = '/tmp/custom "root"/data'
        result = self.resolve(arguments=["helper", "--serve", "--data-root", root],
                              environment={"MAC_CONTROL_DATA_ROOT": "/tmp/ignored"})
        self.assertEqual(result["data"], root)
        self.assertEqual(result["captures"], root + "/run/gui-captures/")

    def test_environment_supports_a_custom_data_root(self):
        self.assertEqual(self.resolve(environment={"MAC_CONTROL_DATA_ROOT": " /tmp/custom/data "})["data"],
                         "/tmp/custom/data")

    def test_invalid_explicit_paths_fail_closed(self):
        for root in ("relative/path", "", "/tmp/a\x00b", "/tmp/" + "я" * 50):
            with self.subTest(root=root):
                self.assertEqual(self.resolve(arguments=["helper", "--data-root", root]), "REJECTED")

    def test_missing_and_duplicate_arguments_fail_closed(self):
        for arguments in (["helper", "--data-root"],
                          ["helper", "--data-root", "/tmp/a", "--data-root", "/tmp/b"]):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.resolve(arguments=arguments), "REJECTED")


if __name__ == "__main__":
    unittest.main()
