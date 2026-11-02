"""maccontrol doctor emits a structured, actionable JSON report."""
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import maccontrol_manager as manager
from scripts import doctor_mac_control as doctor


class DoctorCliTests(unittest.TestCase):
    def test_doctor_prints_machine_readable_status(self):
        fake = doctor.combine({"terminal": {"status": "ready"}})
        with patch.object(doctor, "collect", return_value=fake) as collect:
            output = io.StringIO()
            with redirect_stdout(output):
                code = manager.main(["--root", "/tmp/doctor-fixture", "doctor"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "INCOMPLETE")
        collect.assert_called_once_with(Path("/tmp/doctor-fixture").resolve())


if __name__ == "__main__":
    unittest.main()
