"""Owner-approved absolute SSH transfer file path need not be allowlisted."""
import tempfile,unittest
from pathlib import Path
from mac_control.legacy_handlers.ssh_file_transfer import _safe_local,TransferError
class SSHTransferExternalTests(unittest.TestCase):
 def test_existing_absolute_file_outside_workspace(self):
  with tempfile.TemporaryDirectory(dir="/Users/openclaw/AgentWorkspace") as temp:
   p=Path(temp)/"authorized.bin";p.write_bytes(b"authorized")
   self.assertEqual(_safe_local(str(p),require_existing=True),p)
 def test_symlink_outside_file_rejected(self):
  with tempfile.TemporaryDirectory(dir="/Users/openclaw/AgentWorkspace") as temp:
   base=Path(temp);target=base/"real";target.write_bytes(b"secret")
   alias=base/"alias";alias.symlink_to(target)
   with self.assertRaises(TransferError):
    _safe_local(str(alias),require_existing=True)
if __name__=="__main__":unittest.main()
