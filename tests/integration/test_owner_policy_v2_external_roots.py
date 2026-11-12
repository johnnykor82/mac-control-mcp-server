"""Owner task-authorized external paths work without persistent project allowlist."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from mac_control.legacy_handlers import fs_ops,git_ops,command_plugins

class OwnerExternalProjectTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve()
        self.ws=self.base/"AgentWorkspace";self.ws.mkdir()
        self.external=self.base/"ExplicitOwnerTask";self.external.mkdir()

    def test_explicit_absolute_project_does_not_require_allowlist(self):
        with patch.object(fs_ops,"roots",return_value={"workspace":self.ws}):
            base,file=fs_ops.target_for(str(self.external),"example.txt")
        self.assertEqual(base,self.external.resolve())
        self.assertEqual(file,self.external/"example.txt")
        self.assertEqual(fs_ops.roots.__name__,"roots")

    def test_default_workspace_and_unknown_alias(self):
        with patch.object(fs_ops,"roots",return_value={"workspace":self.ws}):
            self.assertEqual(fs_ops.target_for("workspace","a")[0],self.ws)
            with self.assertRaises((ValueError,PermissionError)):
                fs_ops.target_for("unapproved_alias","a")
            with self.assertRaises(ValueError):
                fs_ops.target_for(str(self.external),"../outside")

    def test_terminal_cwd_external_absolute_project(self):
        with patch.object(command_plugins,"roots",return_value={"workspace":self.ws}),patch.object(fs_ops,"roots",return_value={"workspace":self.ws}):
            self.assertEqual(command_plugins._cwd(str(self.external)),str(self.external.resolve()))

    def test_git_external_absolute_repository_root(self):
        completed=Mock(returncode=0,stdout=str(self.external)+"\n")
        with patch.object(git_ops,"roots",return_value={"workspace":self.ws}),patch.object(fs_ops,"roots",return_value={"workspace":self.ws}),patch.object(git_ops.subprocess,"run",return_value=completed):
            self.assertEqual(git_ops.repo(str(self.external)),self.external.resolve())

    def test_outside_symlink_cannot_escape_external_root(self):
        outside=self.base/"escaped";outside.mkdir()
        (self.external/"jump").symlink_to(outside,target_is_directory=True)
        with patch.object(fs_ops,"roots",return_value={"workspace":self.ws}):
            with self.assertRaises(PermissionError):
                fs_ops.target_for(str(self.external),"jump/hack.txt")

    def test_external_project_parent_symlink_rejected(self):
        real=self.base/"real-parent";real.mkdir()
        nested=real/"approved";nested.mkdir()
        link=self.base/"link-parent";link.symlink_to(real,target_is_directory=True)
        with patch.object(fs_ops,"roots",return_value={"workspace":self.ws}):
            with self.assertRaises(PermissionError):
                fs_ops.root_for_project(str(link/"approved"))
if __name__=="__main__":unittest.main()
