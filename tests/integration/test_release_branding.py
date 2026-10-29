"""Public-facing identity, license, and bilingual navigation checks."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PublicationBrandingTests(unittest.TestCase):
    def test_readmes_switch_languages_from_first_line(self):
        english = (ROOT / "README.md").read_text()
        russian = (ROOT / "README.ru.md").read_text()
        self.assertIn("[Русский](README.ru.md)", english.splitlines()[0])
        self.assertIn("[English](README.md)", russian.splitlines()[0])
        for text in (english, russian):
            self.assertIn("# Mac Control MCP Server", text)
            self.assertIn("ChatBridge", text)

    def test_mit_license_is_packaged(self):
        license_text = (ROOT / "LICENSE").read_text()
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Ivan Konstantinov", license_text)
        from scripts.install_mac_control import COPY_FILES
        self.assertIn("LICENSE", COPY_FILES)
        self.assertIn("README.ru.md", COPY_FILES)

    def test_public_release_description_has_language_switch_in_both_sections(self):
        text = (ROOT / "docs/RELEASE_NOTES_BETA.md").read_text()
        self.assertIn("## English\n\n**Switch language:** [Русский](#русский)", text)
        self.assertIn("## Русский\n\n**Переключить язык:** [English](#english)", text)


if __name__ == "__main__":
    unittest.main()
