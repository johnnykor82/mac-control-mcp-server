"""External user workspace and non-destructive migration regression tests."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from mac_control import workspace_config as wc, workspace_policy as policy
from mac_control.legacy_handlers import fs_ops, command_plugins
from scripts import maccontrol_manager as manager, workspace_migration as migrator


class ExternalWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()/"MacControlMCP"
        self.data=self.root/"data"
        self.data.mkdir(parents=True)
        self.external=self.root.parent/"AgentWorkspace"
        p=patch.object(fs_ops,"ROOT",self.data)
        p.start()
        self.addCleanup(p.stop)

    def test_fresh_install_creates_independent_workspace(self):
        state=wc.provision(self.data,self.root)
        self.assertEqual(state["workspace_root"],str(self.external))
        self.assertFalse(self.external.is_relative_to(self.root))
        self.assertEqual(set(wc.SUBDIRS),{"projects","shared","artifacts","downloads","scratch"})
        self.assertTrue(all((self.external/name).is_dir() for name in wc.SUBDIRS))
        filename=fs_ops.target_for("workspace","projects/new-app/main.py")[1]
        filename.parent.mkdir()
        filename.write_text("print(42)")
        self.assertEqual(filename.read_text(),"print(42)")
        self.assertEqual(fs_ops.roots()["workspace"],self.external)

    def test_dynamic_change_of_workspace(self):
        wc.provision(self.data,self.root)
        custom=self.root.parent/"external custom"
        result=wc.set_root(self.data,custom,self.root)
        self.assertEqual(result["workspace_root"],str(custom))
        self.assertEqual(fs_ops.roots()["workspace"],custom)
        with patch.object(command_plugins,"roots",lambda:{"workspace":custom}):
            self.assertEqual(command_plugins._cwd("workspace"),str(custom))
            self.assertEqual(command_plugins._environment()["TMPDIR"],
                             str(custom/"scratch/tmp"))
        with patch.object(policy,"workspace_root",lambda:custom):
            self.assertIn(str(custom),policy.details()["workspace"])
        self.assertTrue(self.external.is_dir())

    def test_existing_legacy_files_stay_in_place(self):
        old=self.data/"workspace"
        old.mkdir()
        (old/"old.sqlite").write_text("keep")
        self.assertEqual(wc.resolve(self.data)["source"],"legacy_preserved")
        self.assertEqual(wc.provision(self.data,self.root)["workspace_root"],str(old))
        self.assertFalse((self.data/"config/workspace.json").exists())
        self.assertEqual(fs_ops.roots()["workspace"],old)
        self.assertEqual((old/"old.sqlite").read_text(),"keep")

    def test_unavailable_external_disk_refuses_access(self):
        wc.provision(self.data,self.root)
        self.external.rename(self.root.parent/"unplugged")
        with self.assertRaisesRegex(FileNotFoundError,"unavailable"):
            fs_ops.roots()
        self.assertFalse(self.external.exists())

    def test_reinstall_preserves_content_and_configuration(self):
        wc.provision(self.data,self.root)
        file=self.external/"projects/data.txt"
        file.write_text("important")
        self.assertEqual(wc.provision(self.data,self.root)["source"],"configured")
        self.assertEqual(file.read_text(),"important")
        self.assertEqual((self.data/"config/workspace.json").stat().st_mode & 0o777,0o600)

    def test_reject_inside_install_and_symlinks(self):
        with self.assertRaisesRegex(ValueError,"inside"):
            wc.set_root(self.data,self.root/"data/projects",self.root)
        outside=self.root.parent/"external"
        outside.mkdir()
        link=self.root.parent/"link"
        link.symlink_to(outside)
        with self.assertRaises(PermissionError):
            wc.set_root(self.data,link,self.root)

    def test_cli_status_and_set(self):
        (self.root/".mac-control-installer-owned").write_text("owned")
        outside=self.root.parent/"custom"
        self.assertEqual(manager.main(["--root",str(self.root),"workspace","set",str(outside)]),0)
        self.assertTrue(outside.is_dir())
        self.assertEqual(wc.resolve(self.data)["workspace_root"],str(outside))
        self.assertEqual(manager.main(["--root",str(self.root),"workspace","status"]),0)

    def test_migration_dry_run_sqlite_wal_and_symlinks(self):
        wc.provision(self.data,self.root)
        old=self.root.parent/"old"/"workspace"
        old.mkdir(parents=True)
        db=old/"app.sqlite"
        conn=sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE details(id INTEGER, value TEXT)")
        conn.execute("INSERT INTO details VALUES(1, 'WAL committed')")
        conn.commit()
        (old/"file.txt").write_text("original")
        (old/"file-link").symlink_to("file.txt")
        preview=migrator.migrate(old,self.external,"legacy")
        self.assertEqual(preview["mode"],"dry_run")
        self.assertEqual(preview["inventory"]["symlinks"],1)
        self.assertFalse((self.external/"projects/legacy").exists())
        copied=migrator.migrate(old,self.external,"legacy",execute=True,confirmed=True)
        conn.close()
        path=Path(copied["destination"])
        self.assertEqual(copied["status"],"copied_and_verified")
        self.assertEqual((path/"file.txt").read_text(),"original")
        self.assertEqual(os.readlink(path/"file-link"),"file.txt")
        self.assertFalse((path/"app.sqlite-wal").exists())
        with sqlite3.connect(path/"app.sqlite") as database:
            self.assertEqual(database.execute("SELECT value FROM details").fetchone()[0],
                             "WAL committed")
            self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        self.assertTrue(db.exists())
        with self.assertRaises(FileExistsError):
            migrator.migrate(old,self.external,"legacy",execute=True,confirmed=True)

    def test_migration_without_confirmation_has_no_writes(self):
        wc.provision(self.data,self.root)
        old=self.root.parent/"old"
        old.mkdir()
        (old/"file").write_text("preserved")
        with self.assertRaises(PermissionError):
            migrator.migrate(old,self.external,"legacy",execute=True)
        self.assertFalse((self.external/"projects/legacy").exists())
        self.assertEqual((old/"file").read_text(),"preserved")

    def test_interrupted_copy_preserves_source_and_removes_stage(self):
        wc.provision(self.data,self.root)
        old=self.root.parent/"old-work"
        old.mkdir()
        (old/"important").write_text("do not lose")
        with patch.object(migrator,"_copy_verified",side_effect=RuntimeError("interrupted")):
            with self.assertRaisesRegex(RuntimeError,"interrupted"):
                migrator.migrate(old,self.external,"try-copy",execute=True,confirmed=True)
        self.assertEqual((old/"important").read_text(),"do not lose")
        self.assertFalse((self.external/"projects/try-copy").exists())
        self.assertEqual(list((self.external/"projects").glob(".migration-*")),[])

    def test_installer_status_and_uninstall_all_preserve_external_data(self):
        from scripts import install_mac_control as installer, setup_network
        wc.provision(self.data,self.root)
        self.root.chmod(0o700)
        self.data.chmod(0o700)
        keep=self.external/"projects"/"critical.txt"
        keep.write_text("must survive full removal")
        (self.root/".mac-control-installer-owned").write_text("owned")
        (self.root/"releases").mkdir()
        with patch.object(installer,"DEFAULT_ROOT",self.root), \
             patch.object(setup_network,"assert_public_route_safe_for_uninstall",return_value=None), \
             patch.object(installer,"_remove_managed_chatbridge",return_value=False), \
             patch.object(installer,"_uninstall_locked",return_value={"removed_releases":0}):
            report=installer.purge(self.root)
        self.assertEqual(report["status"],"purged")
        self.assertFalse(self.root.exists())
        self.assertEqual(keep.read_text(),"must survive full removal")

    def test_rollback_to_old_release_is_blocked_with_external_workspace(self):
        from scripts import install_mac_control as installer
        wc.provision(self.data,self.root)
        old=self.root/"releases/previous"
        old.mkdir(parents=True)
        (self.root/"previous").symlink_to(old, target_is_directory=True)
        with patch.object(installer,"_verified_release",return_value=old), \
             patch.object(installer,"smoke") as smoke:
            with self.assertRaisesRegex(RuntimeError,"lacks external workspace support"):
                installer.rollback(self.root)
            smoke.assert_not_called()
        self.assertTrue(self.external.is_dir())
        self.assertTrue((self.root/"previous").is_symlink())

    def test_dev_and_stable_defaults_are_distinct(self):
        from mac_control.runtime_paths import DEFAULT_DATA_ROOT
        stable=self.root/"data"
        self.assertNotEqual(wc.default_root(DEFAULT_DATA_ROOT),wc.default_root(stable))
        self.assertEqual(wc.default_root(DEFAULT_DATA_ROOT).name,"AgentWorkspace-Dev")

    def test_inspection_does_not_create_workspace(self):
        old=self.root.parent/"old"
        old.mkdir()
        (old/"text").write_text("preserve")
        self.assertEqual(wc.resolve(self.data)["source"],"default")
        info=migrator.inventory(old,self.external)
        self.assertEqual(info["inventory"]["files"],1)
        self.assertFalse(self.external.exists())


if __name__=="__main__":
    unittest.main()
