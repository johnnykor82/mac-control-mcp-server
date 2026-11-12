"""No disk-backed screenshots or sensitive capture bytes in audit logs."""
from __future__ import annotations

import base64
import inspect
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from mac_control.legacy_handlers import gui_ops

ROOT = Path(__file__).resolve().parents[2]
JPEG = b"\xff\xd8" + b"jpeg-test" + b"\xff\xd9"


class FakeServer:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **options):
        def save(fn):
            self.tools[fn.__name__] = fn
            return fn
        return save


class ScreenshotMemoryTests(TestCase):
    def setUp(self):
        server = FakeServer()
        gui_ops.register(server)
        self.capture = server.tools["gui_screenshot"]

    def test_screenshot_uses_in_memory_native_response_only(self):
        def native(op, **options):
            self.assertEqual(op, "capture")
            self.assertNotIn("destination", options)
            return {"image_data": base64.b64encode(JPEG).decode("ascii"),
                    "pixel_width": 2400, "pixel_height": 1600,
                    "preview_width": 1200, "preview_height": 800,
                    "display_id": 1}
        class NoDisk:
            def mkdir(self, *args, **kwargs):
                raise AssertionError("disk forbidden")
        with patch.object(gui_ops, "_call", side_effect=native), patch.object(
                gui_ops, "CAPTURES", NoDisk()):
            result = self.capture(1200, 1)
        self.assertEqual(result["image_bytes"], len(JPEG))
        self.assertEqual(base64.b64decode(result["image_data"]), JPEG)
        self.assertEqual(result["mime_type"], "image/jpeg")
        self.assertEqual(result["preview_width"], 1200)

    def test_oversize_and_invalid_base64_rejected(self):
        with (
            patch.object(gui_ops, "_call", return_value={
                "image_data": base64.b64encode(JPEG * 300000).decode("ascii")
            }),
            self.assertRaises(ValueError),
        ):
            self.capture()
        with (
            patch.object(gui_ops, "_call", return_value={"image_data": "not***base64"}),
            self.assertRaises(ValueError),
        ):
            self.capture()

    def test_swift_capture_uses_image_data_without_destination_file(self):
        swift = (ROOT / "src/mac_control/assets/gui_agent.swift").read_text()
        capture = swift.split("func capture(_ req:", 1)[1].split("\nfunc ", 1)[0]
        self.assertIn("CGImageDestinationCreateWithData", capture)
        self.assertNotIn("destinationPath", capture)
        self.assertIn("base64EncodedString", capture)
        src = inspect.getsource(self.capture.__wrapped__)
        self.assertNotIn("path.unlink", src)
