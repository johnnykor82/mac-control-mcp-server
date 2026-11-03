"""Installed diagnostics must work without an installer's sys.path."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from mac_control import maintenance_ops as maintenance
from mac_control.legacy_handlers import system_ops, command_plugins, gui_ops
from scripts import setup_tmux_dependency as tmux_install

class Registry:
    def __init__(self):
        self.tools={}
    def tool(self, **kw):
        def store(fn):
            self.tools[fn.__name__]=fn
            return fn
        return store

class InstalledDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home=Path(temporary.name).resolve()
        registry=Registry()
        system_ops.register(registry)
        self.tools=registry.tools

    def test_import_from_installed_src_only_and_poisoned_cwd(self):
        poisoned=self.home/"setup_remote_service.py"
        poisoned.write_text('raise AssertionError("untrusted")\n')
        environment={**os.environ,"PYTHONPATH":str(maintenance.RELEASE_ROOT/"src"),
                     "PYTHONNOUSERSITE":"1"}
        process=subprocess.run([sys.executable,"-P","-B","-c",
            'from mac_control.maintenance_ops import _service_helper; '
            's=_service_helper(); assert s.LABEL=="org.maccontrol.mcpserver.remote"; '
            'assert s.PORT==3201'],cwd=self.home,env=environment,
            capture_output=True,text=True,timeout=15)
        self.assertEqual(process.returncode,0,process.stderr)

    def test_reject_symlinked_shipped_helper(self):
        malicious=self.home/"release/scripts"
        malicious.mkdir(parents=True)
        (malicious/"setup_remote_service.py").symlink_to(self.home/"poison.py")
        (malicious/"setup_github_oauth.py").write_text("pass\n")
        with patch.object(maintenance,"RELEASE_ROOT",malicious.parent):
            with self.assertRaisesRegex(RuntimeError,"not trustworthy"):
                maintenance._service_helper()

    def test_mcp_diagnostics_returns_running_pid_and_logs(self):
        registry=Registry()
        maintenance.register(registry)
        with patch.object(maintenance,"_owned_service",return_value=(
            self.home/"helper",{"status":"running","pid":"15093",
                                "label":"org.maccontrol.mcpserver.remote"})):
            result=registry.tools["mcp_diagnostics"]()
        self.assertEqual(result["launchd"]["pid"],"15093")
        self.assertIn("log_bytes",result)
        self.assertIn("active_pid",result)

    def test_launchd_default_and_watcher_and_old_label(self):
        service=Mock(LABEL="org.maccontrol.mcpserver.remote",PORT=3201)
        with patch.object(system_ops,"_managed_service",return_value=service), \
             patch.object(system_ops,"execute",return_value={
               "exit_code":0,"stdout":"state = running\npid = 15093\n",
               "stderr":""}) as run:
            result=self.tools["launchd_status"]()
            self.assertEqual(result["label"],service.LABEL)
            self.assertEqual(result["pid"],15093)
            self.assertEqual(result["state"],"running")
            self.assertIn(service.LABEL,run.call_args.args[0][-1])
            watcher=self.tools["launchd_status"]("org.maccontrol.mcpserver.watcher")
            self.assertEqual(watcher["label"],"org.maccontrol.mcpserver.watcher")
            for label in ("net.chatbridge.gateway", "net.chatbridge.gateway.maccontrol",
                          "net.johnnykor.chatgpt-mcp"):
                status = self.tools["launchd_status"](label)
                self.assertEqual(status["label"], label)
                self.assertIn(f"gui/{os.getuid()}/{label}", run.call_args.args[0])

    def test_launchd_restart_no_local_label_allowlist_and_no_shell(self):
        service = Mock(LABEL="org.maccontrol.mcpserver.remote", PORT=3201)
        with patch.object(system_ops, "_managed_service", return_value=service), \
             patch.object(system_ops, "execute", return_value={
                 "exit_code": 0, "stdout": "", "stderr": ""}) as run:
            for label in ("net.chatbridge.gateway", "net.chatbridge.gateway.maccontrol"):
                result = self.tools["launchd_restart"](label)
                self.assertEqual(result["exit_code"], 0)
                run.assert_called_with(
                    ["/bin/launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"],
                    str(Path.home()), 20)
            with self.assertRaisesRegex(ValueError, "restart_server"):
                self.tools["launchd_restart"](service.LABEL)
            self.assertEqual(run.call_count, 2)

    def test_launchd_invalid_labels_rejected_without_running_any_command(self):
        service = Mock(LABEL="org.maccontrol.mcpserver.remote", PORT=3201)
        invalid = ("../other", "../../etc/passwd", "net.bad;touch", "a/b", " ",
                   "bad label", "a" * 121, "-a\n")
        with patch.object(system_ops, "_managed_service", return_value=service), \
             patch.object(system_ops, "execute") as run:
            for label in invalid:
                with self.subTest(label=label):
                    with self.assertRaises(ValueError):
                        self.tools["launchd_status"](label)
                    with self.assertRaises(ValueError):
                        self.tools["launchd_restart"](label)
            run.assert_not_called()

    def test_local_probe_uses_installed_port_and_does_not_follow_redirects(self):
        class Response:
            status=200
            headers={"content-type":"application/json"}
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,n): return b'{"issuer":"https://test.ts.net"}'
        opener=Mock()
        opener.open.return_value=Response()
        service=Mock(PORT=3201,LABEL="org.maccontrol.mcpserver.remote")
        with patch.object(system_ops,"_managed_service",return_value=service), \
             patch.object(system_ops.urllib.request,"build_opener",return_value=opener):
            result=self.tools["local_http_probe"](
                path="/.well-known/oauth-authorization-server")
            self.assertEqual(result["status"],200)
            self.assertEqual(opener.open.call_args.args[0].full_url,
                "http://127.0.0.1:3201/.well-known/oauth-authorization-server")
            self.assertEqual(self.tools["local_http_probe"](port=3201)["status"],200)
            with self.assertRaises(PermissionError):
                self.tools["local_http_probe"](port=65001)
            with self.assertRaises(ValueError):
                self.tools["local_http_probe"](path="/../../secret")
    def test_tmux_missing_returns_structured_error_without_calling_tmux(self):
        registry=Registry()
        with patch.object(command_plugins,"_require"), \
             patch.object(command_plugins,"_tmux_available",return_value=None), \
             patch.object(command_plugins,"_tmux") as process:
            command_plugins.register(registry)
            for name in ("terminal_list","terminal_open","terminal_read",
                         "terminal_send","terminal_resize","terminal_close"):
                params={} if name in ("terminal_list","terminal_open") else {
                    "session":"mc-"+"0"*16}
                result=registry.tools[name](**params)
                self.assertEqual(result["error"]["code"],"TMUX_NOT_INSTALLED")
                self.assertIn("brew install tmux",result["remedy"])
            process.assert_not_called()

    def test_tmux_install_requires_owner_permission(self):
        with patch.object(tmux_install,"locate",return_value=None), \
             patch.object(tmux_install.shutil,"which",
                          side_effect=lambda name:
                            "/opt/homebrew/bin/brew" if name=="brew" else None), \
             patch.object(tmux_install.Path,"is_file",return_value=True), \
             patch.object(tmux_install.os,"access",return_value=True), \
             patch.object(tmux_install.subprocess,"run") as process:
            self.assertEqual(tmux_install.ensure()["status"],"needs_owner_approval")
            self.assertEqual(tmux_install.ensure(interactive=True,input_fn=lambda _: "no")["status"],
                             "needs_owner_approval")
            process.assert_not_called()
            process.return_value.returncode=0
            self.assertEqual(tmux_install.ensure(approved=True)["status"],"install_failed")
            self.assertEqual(process.call_args.args[0],
                             ["/opt/homebrew/bin/brew","install","tmux"])

    def test_homebrew_receives_user_environment_and_reports_error(self):
        with patch.object(tmux_install,"locate",return_value=None), \
             patch.object(tmux_install,"_homebrew",return_value="/opt/homebrew/bin/brew"), \
             patch.object(tmux_install.subprocess,"run") as process, \
             patch.dict(os.environ,{"USER":"jk","LOGNAME":"jk",
                                    "TMPDIR":"/tmp/jk-tmp",
                                    "HTTPS_PROXY":"http://proxy.test:8080",
                                    "LANG":"ru_RU.UTF-8"}):
            process.return_value.returncode=1
            process.return_value.stderr="Error: Homebrew needs writable cache directory"
            process.return_value.stdout="==> Downloading tmux"
            result=tmux_install.ensure(approved=True)
            self.assertEqual(result["status"],"install_failed")
            self.assertEqual(result["error_code"],"HOMEBREW_INSTALL_FAILED")
            self.assertIn("writable cache",result["stderr_tail"])
            self.assertIn("Downloading",result["stdout_tail"])
            env=process.call_args.kwargs["env"]
            self.assertEqual(env["USER"],"jk")
            self.assertEqual(env["LOGNAME"],"jk")
            self.assertEqual(env["TMPDIR"],"/tmp/jk-tmp")
            self.assertEqual(env["HTTPS_PROXY"],"http://proxy.test:8080")
            self.assertEqual(env["LANG"],"ru_RU.UTF-8")
            self.assertIn("/opt/homebrew/bin",env["PATH"])
            self.assertEqual(env["HOMEBREW_NO_AUTO_UPDATE"],"1")

    def test_homebrew_timeout_and_missing_binary_are_structured(self):
        with patch.object(tmux_install,"locate",return_value=None), \
             patch.object(tmux_install,"_homebrew",return_value="/opt/homebrew/bin/brew"), \
             patch.object(tmux_install.subprocess,"run") as process:
            process.side_effect=subprocess.TimeoutExpired(
                ["brew","install","tmux"],360,output=b"fetching...",stderr=b"timed out")
            result=tmux_install.ensure(approved=True)
            self.assertEqual(result["error_code"],"HOMEBREW_TIMEOUT")
            self.assertFalse(result["available"])
            process.side_effect=None
            process.return_value.returncode=0
            process.return_value.stderr=""
            process.return_value.stdout=""
            result=tmux_install.ensure(approved=True)
            self.assertEqual(result["error_code"],"TMUX_BINARY_UNUSABLE")

    def test_homebrew_exit_one_with_working_tmux_is_available_with_warning(self):
        from subprocess import CompletedProcess
        with patch.object(tmux_install, "locate",
                          side_effect=[None, "/opt/homebrew/bin/tmux"]), \
             patch.object(tmux_install, "_homebrew",
                          return_value="/opt/homebrew/bin/brew"), \
             patch.object(tmux_install.subprocess, "run",
                          side_effect=[
                            CompletedProcess(["brew"],1,"Install finished",
                                             "Homebrew cleanup failed"),
                            CompletedProcess(["tmux","-V"],0,"tmux 3.8\n","")
                          ]) as run:
            state=tmux_install.ensure(approved=True)
        self.assertEqual(state["status"],"installed_with_warnings")
        self.assertTrue(state["available"])
        self.assertEqual(state["version"],"tmux 3.8")
        self.assertEqual(state["exit_code"],1)
        self.assertIn("cleanup failed",state["stderr_tail"])
        self.assertEqual(run.call_args.args[0],
                         ["/opt/homebrew/bin/tmux","-V"])

    def test_homebrew_exit_zero_with_working_tmux_is_installed(self):
        from subprocess import CompletedProcess
        with patch.object(tmux_install, "locate",
                          side_effect=[None, "/opt/homebrew/bin/tmux"]), \
             patch.object(tmux_install, "_homebrew",
                          return_value="/opt/homebrew/bin/brew"), \
             patch.object(tmux_install.subprocess, "run",
                          side_effect=[
                            CompletedProcess(["brew"],0,"",""),
                            CompletedProcess(["tmux","-V"],0,"tmux 3.8\n","")
                          ]):
            state=tmux_install.ensure(approved=True)
        self.assertEqual(state["status"],"installed")
        self.assertTrue(state["available"])
        self.assertEqual(state["version"],"tmux 3.8")

    def test_tmux_logs_redact_secrets(self):
        value=("error: AUTHORIZATION Bearer secret-value" + chr(10)
               + "error: token=personal-secret" + chr(10)
               + "Error: cannot write to /opt/homebrew/Cellar")
        result=tmux_install._excerpt(value)
        self.assertNotIn("secret-value",result)
        self.assertNotIn("personal-secret",result)
        self.assertIn("Cellar",result)

    def test_tmux_existing_binary_does_not_invoke_brew(self):
        with patch.object(tmux_install,"locate",return_value="/opt/homebrew/bin/tmux"), \
             patch.object(tmux_install.subprocess,"run") as process:
            status=tmux_install.ensure(approved=True)
            self.assertEqual(status["status"],"ready")
            process.assert_not_called()

    def test_terminal_sessions_open_read_send_close_after_dependency_available(self):
        registry=Registry()
        actions=[]
        def tmux_fake(argv,**kwargs):
            actions.append(argv)
            name=argv[0]
            if name=="new-session":
                return subprocess.CompletedProcess(argv,0,"","")
            if name=="has-session":
                return subprocess.CompletedProcess(argv,0,"","")
            if name=="capture-pane":
                return subprocess.CompletedProcess(argv,0,"command printed output","")
            if name=="list-sessions":
                return subprocess.CompletedProcess(argv,0,
                      "mc-0123456789abcdef|1762012800|0\n","")
            return subprocess.CompletedProcess(argv,0,"","")
        with patch.object(command_plugins,"_require"), \
             patch.object(command_plugins,"_tmux_available",return_value="/opt/homebrew/bin/tmux"), \
             patch.object(command_plugins,"_tmux",side_effect=tmux_fake), \
             patch.object(command_plugins,"_cwd",return_value=str(self.home)):
            command_plugins.register(registry)
            opened=registry.tools["terminal_open"]()
            name=opened["session"]
            self.assertTrue(name.startswith("mc-"))
            self.assertEqual(registry.tools["terminal_read"](name)["screen"],
                             "command printed output")
            self.assertEqual(registry.tools["terminal_send"](name,text="print(42)",
                             key="Enter")["status"],"sent")
            self.assertEqual(registry.tools["terminal_resize"](name)["cols"],120)
            self.assertEqual(len(registry.tools["terminal_list"]()["sessions"]),1)
            self.assertEqual(registry.tools["terminal_close"](name)["closed"],name)
        self.assertIn("new-session",[x[0] for x in actions])
        self.assertIn("send-keys",[x[0] for x in actions])
        self.assertIn("kill-session",[x[0] for x in actions])

    def test_install_tmux_option_is_forwarded_to_installer(self):
        from scripts import maccontrol_manager as manager
        with patch.object(manager,"latest_beta",return_value=("v0.1.0-beta.23",{})), \
             patch.object(manager,"verified_archive",return_value=b"archive"), \
             patch.object(manager,"unpack_release") as unpack, \
             patch.object(manager.subprocess,"call",return_value=0) as call:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp)/"MacControlMCP"
                root.mkdir()
                (root/".mac-control-installer-owned").write_text("owned")
                unpack.return_value=Path(temp)/"unpacked"
                self.assertEqual(manager.update(root,install_tmux=True),0)
            self.assertIn("--install-tmux",call.call_args.args[0])

    def test_gui_responsive_even_when_pid_unobserved(self):
        registry=Registry()
        gui_ops.register(registry)
        with patch.object(gui_ops,"_status",return_value={
                "accessibility_trusted":True,"screen_capture_trusted":True}), \
             patch.object(gui_ops._gui_ipc,"diagnostics",return_value={
                "helper_pid":None,"service_state":"not_running"}):
            status=registry.tools["gui_status"]()
            self.assertEqual(status["functional_state"],"operational")
            self.assertEqual(status["ipc"]["service_state"],"responsive")
            self.assertEqual(status["ipc"]["process_detection"],"not_observed")
            self.assertEqual(status["ipc"]["launch_mode"],"on_demand")

if __name__=="__main__":
    unittest.main()
