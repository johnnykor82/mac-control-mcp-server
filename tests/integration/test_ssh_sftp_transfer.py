"""SFTP integration-contract tests using a real local remote commit helper.

Only the transport is simulated (copying bytes); paths, hashes, atomic
publication, session persistence and remote helper code are exercised.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mac_control.legacy_handlers import ssh_file_transfer as tf
from mac_control.legacy_handlers.ssh_file_remote import REMOTE_HELPER


class SftpTransferTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = Path(t.name).resolve()
        self.remote = self.home / "remote"
        self.remote.mkdir()
        self.local = self.home / "local"
        self.local.mkdir()
        self.session_root = self.home / "transfers"
        self.logs = self.home / "data"
        self.logs.mkdir()
        self.patches = [
            patch.object(tf, "STAGING", self.session_root),
            patch.object(tf, "DATA_ROOT", self.logs),
            patch.object(tf, "_safe_local", side_effect=lambda path,require_existing=False:Path(path)),
            patch.object(tf.ssh, "_spec", return_value={"kind":"alias","alias":"test"}),
            patch.object(tf, "_remote", side_effect=self.remote_helper),
            patch.object(tf, "_sftp", side_effect=self.sftp),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.interrupt_once = False
        self.sftp_calls = []

    def remote_helper(self, host, action, path, *arguments):
        proc = subprocess.run([sys.executable,"-c",REMOTE_HELPER, action,path,*map(str,arguments)],
                              text=True,capture_output=True,
                              env={**os.environ,"HOME":str(self.home)})
        try:
            data=json.loads(proc.stdout)
        except ValueError:
            self.fail("Remote helper invalid: "+proc.stdout+proc.stderr)
        if not data["ok"]:
            raise tf.TransferError(data["code"])
        return data["result"]

    def sftp(self, host, instruction, timeout=240):
        self.sftp_calls.append(instruction)
        action, origin, dest = shlex.split(instruction)
        if action not in ("put","reput","get"):
            self.fail("Unsupported SFTP command: "+instruction)
        copied = 0
        with open(origin,"rb") as inp, open(dest,"ab" if action=="reput" else "wb") as out:
            if action=="reput":
                inp.seek(out.tell())
            while True:
                chunk=inp.read(32768)
                if not chunk:
                    break
                out.write(chunk)
                copied+=len(chunk)
                if self.interrupt_once and copied > 1000:
                    self.interrupt_once=False
                    raise tf.TransferError("ssh_disconnected",retryable=True,resumable=True)

    def sample(self, size, name="sample.txt"):
        path=self.local/name
        data=(b"abc123-xyz\n"*(size//11+1))[:size]
        path.write_bytes(data)
        return path

    def test_15kb_text_and_unicode_filename(self):
        path=self.sample(15*1024,"исходник Unicode.py")
        dest=self.remote/"скрипт «тест».py"
        result=tf.write_text("test",str(dest),path.read_text(),overwrite=False)
        self.assertTrue(result["verified"])
        self.assertEqual(path.read_bytes(),dest.read_bytes())
        self.assertIn("put ",self.sftp_calls[0])
        self.assertEqual(result["sha256"],hashlib.sha256(path.read_bytes()).hexdigest())

    def test_100kb_python_and_10mb_binary(self):
        code="# generated\n"+("value=42 # comment line\n"*5000)
        path=self.remote/"generated.py"
        r=tf.write_text("test",str(path),code)
        self.assertEqual(path.read_text(),code)
        self.assertTrue(r["verified"])
        compile(path.read_bytes(),str(path),"exec")
        source=self.sample(10*1024*1024,"large.bin")
        dest=self.remote/"large.bin"
        r=tf.upload("test",str(source),str(dest))
        self.assertEqual(r["size_bytes"],10*1024*1024)
        self.assertEqual(tf._sha(source),tf._sha(dest))

    def test_download_hash_atomic_and_preserves_existing(self):
        source=self.sample(100000)
        remote=self.remote/"download.txt"
        shutil.copyfile(source,remote)
        dest=self.local/"downloaded.txt"
        r=tf.download("test",str(remote),str(dest),expected_sha256=tf._sha(remote))
        self.assertEqual(r["sha256"],tf._sha(dest))
        self.assertEqual(dest.read_bytes(),source.read_bytes())
        with self.assertRaisesRegex(tf.TransferError,"file_exists"):
            tf.download("test",str(remote),str(dest))
        self.assertEqual(dest.read_bytes(),source.read_bytes())

    def test_wrong_download_hash_preserves_destination(self):
        remote=self.remote/"original.bin"
        remote.write_bytes(b"secret payload")
        local=self.local/"keep.bin"
        local.write_bytes(b"keep me")
        with self.assertRaisesRegex(tf.TransferError,"hash_mismatch"):
            tf.download("test",str(remote),str(local),overwrite=True,expected_sha256="0"*64)
        self.assertEqual(local.read_bytes(),b"keep me")
        self.assertFalse(list(self.local.glob(".maccontrol-download-*")))

    def test_transfer_audit_contains_metadata_not_payload(self):
        content="Sensitive content that must not be in transfer logs."
        dest=self.remote/"audit.txt"
        result=tf._wrap("ssh_write_text","test",str(dest),None,
                        lambda:tf.write_text("test",str(dest),content))
        self.assertEqual(result["status"],"completed")
        raw=(self.logs/"logs/ssh-transfers.jsonl").read_text()
        event=json.loads(raw.splitlines()[-1])
        self.assertEqual(event["operation"],"ssh_write_text")
        self.assertEqual(event["host"],"test")
        self.assertEqual(event["sha256"],result["sha256"])
        self.assertNotIn(content,raw)

    def test_overwrite_with_sha_cas_and_refuse_conflict(self):
        dest=self.remote/"existing.txt"
        dest.write_text("old")
        old=tf._sha(dest)
        with self.assertRaisesRegex(tf.TransferError,"file_exists"):
            tf.write_text("test",str(dest),"new")
        with self.assertRaisesRegex(tf.TransferError,"cas_conflict"):
            tf.write_text("test",str(dest),"new",overwrite=True,
                          expected_remote_sha256="0"*64)
        self.assertEqual(dest.read_text(),"old")
        r=tf.write_text("test",str(dest),"new",overwrite=True,
                        expected_remote_sha256=old)
        self.assertTrue(r["verified"])
        self.assertEqual(dest.read_text(),"new")

    def test_remote_symlink_rejected(self):
        target=self.remote/"real.txt"
        target.write_text("protected")
        (self.remote/"alias.txt").symlink_to(target)
        with self.assertRaisesRegex(tf.TransferError,"unsafe_symlink"):
            tf.write_text("test",str(self.remote/"alias.txt"),"evil",overwrite=True)
        self.assertEqual(target.read_text(),"protected")

    def test_interruption_resume_sftp_and_no_partial_final(self):
        source=self.sample(150000)
        dest=self.remote/"resume.bin"
        started=tf.begin("upload","test",str(dest),total_size=source.stat().st_size)
        token=started["transfer_id"]
        for i,position in enumerate(range(0,source.stat().st_size,tf.CHUNK_LIMIT)):
            data=source.read_bytes()[position:position+tf.CHUNK_LIMIT]
            tf.chunk(token,position,i,base64.b64encode(data).decode(),hashlib.sha256(data).hexdigest())
        self.interrupt_once=True
        with self.assertRaisesRegex(tf.TransferError,"ssh_disconnected"):
            tf.finish(token)
        self.assertFalse(dest.exists())
        self.assertTrue((self.session_root/token/"meta.json").exists())
        result=tf.finish(token)
        self.assertEqual(result["sha256"],tf._sha(source))
        self.assertEqual(tf._sha(dest),tf._sha(source))
        self.assertTrue(any(s.startswith("reput ") for s in self.sftp_calls))
        self.assertFalse((self.session_root/token).exists())

    def test_chunk_retries_offsets_and_persistent_state(self):
        dest=self.remote/"persist.txt"
        started=tf.begin("upload","test",str(dest),total_size=9)
        tid=started["transfer_id"]
        data=b"123456789"
        encoded=base64.b64encode(data).decode()
        sha=hashlib.sha256(data).hexdigest()
        first=tf.chunk(tid,0,0,encoded,sha)
        self.assertEqual(first["next_offset"],9)
        self.assertEqual(tf.chunk(tid,0,0,encoded,sha)["status"],"already_accepted")
        with self.assertRaisesRegex(tf.TransferError,"invalid_offset"):
            tf.chunk(tid,4,1,encoded,sha)
        with self.assertRaisesRegex(tf.TransferError,"invalid_chunk_hash_or_size"):
            tf.chunk(tid,9,1,encoded,"0"*64)
        self.assertEqual(json.loads((self.session_root/tid/"meta.json").read_text())["next_offset"],9)
        tf.finish(tid)
        self.assertEqual(dest.read_bytes(),data)

    def test_bad_checksum_and_cancel(self):
        dest=self.remote/"never_publish.txt"
        tid=tf.begin("upload","test",str(dest),total_size=5)["transfer_id"]
        data=b"abcde"
        tf.chunk(tid,0,0,base64.b64encode(data).decode(),hashlib.sha256(data).hexdigest())
        with self.assertRaisesRegex(tf.TransferError,"hash_mismatch"):
            tf.finish(tid,"0"*64)
        self.assertFalse(dest.exists())
        self.assertEqual(tf.cancel(tid)["status"],"cancelled")
        self.assertFalse((self.session_root/tid).exists())

    def test_download_streamed_chunks(self):
        source=self.remote/"remote.bin"
        source.write_bytes(b"\x00\xffhello\n"*10000)
        tid=tf.begin("download","test",str(source),total_size=None)["transfer_id"]
        pieces=[]
        offset=0
        idx=0
        while True:
            item=tf.chunk(tid,offset,idx)
            part=base64.b64decode(item["data_base64"])
            self.assertEqual(hashlib.sha256(part).hexdigest(),item["chunk_sha256"])
            pieces.append(part)
            offset=item["next_offset"]
            idx+=1
            if item["eof"]:
                break
        self.assertEqual(b"".join(pieces),source.read_bytes())
        result=tf.finish(tid)
        self.assertEqual(result["sha256"],tf._sha(source))

    def test_streaming_100mb_bounded_chunks(self):
        size=100*1024*1024
        dest=self.remote/"100mb.bin"
        tid=tf.begin("upload","test",str(dest),total_size=size)["transfer_id"]
        segment=b"z"*tf.CHUNK_LIMIT
        encoded=base64.b64encode(segment).decode()
        digest=hashlib.sha256(segment).hexdigest()
        for index in range(size//tf.CHUNK_LIMIT):
            result=tf.chunk(tid,index*tf.CHUNK_LIMIT,index,encoded,digest)
        self.assertEqual(result["next_offset"],size)
        completed=tf.finish(tid)
        self.assertEqual(completed["size_bytes"],size)
        self.assertEqual(dest.stat().st_size,size)
        self.assertEqual(completed["sha256"],tf._sha(dest))

    def test_resume_via_transfer_begin_and_total_size_limit(self):
        dest=self.remote/"resume-token.bin"
        first=tf.begin("upload","test",str(dest),total_size=10)
        tid=first["transfer_id"]
        chunk=b"abc"
        tf.chunk(tid,0,0,base64.b64encode(chunk).decode(),hashlib.sha256(chunk).hexdigest())
        resumed=tf.begin("upload","test",str(dest),resume_transfer_id=tid)
        self.assertEqual(resumed["next_offset"],3)
        self.assertEqual(resumed["transfer_id"],tid)
        with self.assertRaisesRegex(tf.TransferError,"transfer_identity_conflict"):
            tf.begin("upload","test",str(self.remote/"other"),resume_transfer_id=tid)
        self.assertEqual(tf.cancel(tid)["status"],"cancelled")
        self.assertEqual(tf.cancel(tid)["status"],"already_cancelled")

    def test_owner_policy_overrides_limits(self):
        settings=self.logs/"ssh_transfer_policy.json"
        settings.write_text(json.dumps({"max_chunk_bytes":1024,"ttl_seconds":600,
                                        "max_total_bytes":1048576}))
        settings.chmod(0o600)
        started=tf.begin("upload","test",str(self.remote/"policy.bin"))
        self.assertEqual(started["max_chunk_bytes"],1024)
        with self.assertRaisesRegex(tf.TransferError,"size_limit"):
            tf.begin("upload","test",str(self.remote/"large.bin"),total_size=100*1024*1024)
        with self.assertRaisesRegex(tf.TransferError,"chunk_too_large"):
            payload=base64.b64encode(b"x"*2000).decode()
            tf.chunk(started["transfer_id"],0,0,payload,hashlib.sha256(b"x"*2000).hexdigest())

    def test_expired_session_is_cleaned_on_next_transfer(self):
        dest=self.remote/"expired.bin"
        tid=tf.begin("upload","test",str(dest))["transfer_id"]
        metadata=self.session_root/tid/"meta.json"
        os.utime(metadata,(0,0))
        started=tf.begin("upload","test",str(self.remote/"new.bin"))
        self.assertFalse((self.session_root/tid).exists())
        tf.cancel(started["transfer_id"])

    def test_remote_stage_cleanup_after_failure(self):
        source=self.sample(150000)
        dest=self.remote/"interrupted.bin"
        tid=tf.begin("upload","test",str(dest))["transfer_id"]
        for i,pos in enumerate(range(0,source.stat().st_size,tf.CHUNK_LIMIT)):
            with source.open("rb") as f:
                f.seek(pos)
                data=f.read(tf.CHUNK_LIMIT)
            tf.chunk(tid,pos,i,base64.b64encode(data).decode(),hashlib.sha256(data).hexdigest())
        self.interrupt_once=True
        with self.assertRaisesRegex(tf.TransferError,"ssh_disconnected"):
            tf.finish(tid)
        parts=list(self.remote.glob("*.part"))
        self.assertTrue(parts)
        self.assertEqual(tf.cancel(tid)["status"],"cancelled")
        self.assertFalse(list(self.remote.glob("*.part")))
        self.assertFalse(dest.exists())

    def test_legacy_owner_approved_ssh_profile_adapter(self):
        legacy=["/usr/bin/ssh","-F","/dev/null","-T","-p","23827",
                "-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
                "--","example@127.0.0.1"]
        with patch.object(tf.ssh,"_command",side_effect=PermissionError("Host is not approved")), \
             patch.object(tf.legacy_ssh,"_argv",return_value=legacy+["id -un"]) as legacy_builder:
            args=tf._sftp_argv("registered-legacy")
            self.assertEqual(args[-1],"example@127.0.0.1")
            self.assertIn("StrictHostKeyChecking=yes",args)
            self.assertIn("-P",args)
            self.assertNotIn("-T",args)
            legacy_builder.assert_called_once_with("registered-legacy","identity")
        with patch.object(tf.ssh,"_command",side_effect=PermissionError("SSH host config unsafe")), \
             patch.object(tf.legacy_ssh,"_argv") as legacy_builder:
            with self.assertRaisesRegex(PermissionError,"config unsafe"):
                tf._ssh_command("registered-legacy")
            legacy_builder.assert_not_called()

    def test_sftp_options_reuse_profile_with_host_key_check(self):
        args=["/usr/bin/ssh","-o","BatchMode=yes","-o","StrictHostKeyChecking=yes",
              "-F","/dev/null","-p","22333","-T","--","user@127.0.0.1"]
        with patch.object(tf.ssh,"_command",return_value=args):
            out=tf._sftp_argv("test")
        self.assertIn("StrictHostKeyChecking=yes",out)
        self.assertIn("-P",out)
        self.assertNotIn("-T",out)
        self.assertEqual(out[-1],"user@127.0.0.1")


if __name__=="__main__":
    unittest.main()
