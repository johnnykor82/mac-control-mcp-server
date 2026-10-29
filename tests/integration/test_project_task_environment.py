"""Project tests must use the project's dependencies, never the MCP runtime."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mac_control.legacy_handlers import system_ops


class Registry:
    def __init__(self):
        self.tools = {}

    def tool(self, **kwargs):
        def decorate(function):
            self.tools[function.__name__] = function
            return function
        return decorate


class ProjectTaskEnvironmentTests(unittest.TestCase):
    def test_pytest_uses_project_virtualenv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.touch(mode=0o700)
            registry = Registry()
            system_ops.register(registry)
            with patch.object(system_ops, "roots", return_value={"demo": root}), \
                 patch.object(system_ops, "execute", return_value={}) as execute:
                registry.tools["project_task"]("demo", "pytest")
            self.assertEqual(execute.call_args.args[0][0], str(python))

    def test_missing_project_virtualenv_gives_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = Registry()
            system_ops.register(registry)
            with patch.object(system_ops, "roots", return_value={"demo": Path(temporary)}):
                with self.assertRaisesRegex(ValueError, "execute_approved"):
                    registry.tools["project_task"]("demo", "pytest")
