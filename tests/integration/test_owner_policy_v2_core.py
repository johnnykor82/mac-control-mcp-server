"""Owner-policy v2: core diagnostics must not have artificial allowlists."""
import subprocess
import unittest
from unittest.mock import Mock, patch

from mac_control.legacy_handlers import system_ops
from mac_control import maintenance_ops

class Registry:
    def __init__(self): self.tools = {}
    def tool(self, **kwargs):
        def register(fn):
            self.tools[fn.__name__] = fn
            return fn
        return register

class OwnerPolicyCoreTests(unittest.TestCase):
    def setUp(self):
        r=Registry(); system_ops.register(r); self.system=r.tools
        q=Registry(); maintenance_ops.register(q); self.maintenance=q.tools

    def test_local_probe_any_loopback_port_and_path_without_redirect(self):
        response=Mock(status=200, headers={"content-type":"application/json"})
        response.read.return_value=b'{"ready":true}'
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        opener=Mock(); opener.open.return_value=response
        service=Mock(PORT=3201)
        with patch.object(system_ops, "_managed_service", return_value=service), patch.object(
                system_ops.urllib.request, "build_opener",return_value=opener):
            self.assertEqual(self.system["local_http_probe"](8769,"/health")["status"],200)
            self.assertEqual(opener.open.call_args.args[0].full_url,"http://127.0.0.1:8769/health")
            self.assertEqual(self.system["local_http_probe"](8769,"/v1/system/status")["status"],200)
            self.assertEqual(self.system["local_http_probe"](65001,"/any/route")["status"],200)
            for port in (0,65536,True,"8769"):
                with self.subTest(port=port), self.assertRaises(ValueError):
                    self.system["local_http_probe"](port)
            with self.assertRaises(ValueError):
                self.system["local_http_probe"](8769,"/../../secret")
            with self.assertRaises(ValueError):
                self.system["local_http_probe"](8769,"/%2e%2e/secret")
            with self.assertRaises(ValueError):
                self.system["local_http_probe"](8769,"/health\r\nHeader: x")

    def test_process_snapshot_lists_unrelated_process_without_argv(self):
        output='100 1 0.0 1.0 4000 /usr/bin/python3\n101 1 0.0 1.0 2000 /usr/bin/unrelated\n'
        with patch.object(maintenance_ops.subprocess,"run",return_value=subprocess.CompletedProcess([],0,output,"")) as run:
            result=self.maintenance["process_snapshot"]()
        self.assertEqual(result["total_matched"],2)
        self.assertEqual({p["executable"] for p in result["processes"]},{"python3","unrelated"})
        self.assertNotIn("args"," ".join(run.call_args.args[0]))

    def test_project_task_accepts_explicit_command_without_shell(self):
        fake=Mock(return_value={"exit_code":0})
        from mac_control.legacy_handlers import fs_ops
        with patch.object(fs_ops,"roots",return_value={"workspace":__import__("pathlib").Path("/tmp/workspace")}),patch.object(system_ops,"execute",fake):
            result=self.system["project_task"]("workspace","/usr/bin/true --version")
        self.assertEqual(result["exit_code"],0)
        self.assertEqual(fake.call_args.args[0],["/usr/bin/true","--version"])
        self.assertEqual(fake.call_args.args[1],str(__import__("pathlib").Path("/tmp/workspace").resolve()))


    def test_process_snapshot_can_return_over_one_hundred_processes(self):
        output="".join(f"{i} 1 0.0 0.1 50 /usr/bin/app{i}\n" for i in range(200))
        with patch.object(maintenance_ops.subprocess,"run",
                          return_value=subprocess.CompletedProcess([],0,output,"")):
            result=self.maintenance["process_snapshot"](limit=200)
        self.assertEqual(result["total_matched"],200)
        self.assertEqual(len(result["processes"]),200)

if __name__ == "__main__":
    unittest.main()
