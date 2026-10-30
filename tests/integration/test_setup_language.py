"""Setup language choice is explicit, shared, and does not change authorization."""
import io
import plistlib
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from scripts import guided_setup, setup_github_oauth, setup_language


class SetupLanguageTests(unittest.TestCase):
    def test_macos_uses_first_preferred_language(self):
        for preferred, expected in ((["ru-RU", "en-US"], "ru"), (["en-US", "ru-RU"], "en"), (["fr-FR"], "en")):
            with self.subTest(preferred=preferred), \
                 patch.object(setup_language.sys, "platform", "darwin"), \
                 patch.object(setup_language.subprocess, "run", return_value=SimpleNamespace(
                     stdout=plistlib.dumps({"AppleLanguages": preferred}))):
                self.assertEqual(setup_language.detect_language(), expected)

    def test_locale_fallback_and_unsupported_language(self):
        for locale, expected in (("ru_RU.UTF-8", "ru"), ("en_US.UTF-8", "en"), ("de_DE.UTF-8", "en")):
            with self.subTest(locale=locale), \
                 patch.object(setup_language.sys, "platform", "linux"), \
                 patch.dict(setup_language.os.environ, {"LANG": locale}, clear=True):
                self.assertEqual(setup_language.detect_language(), expected)

    def test_enter_accepts_system_default_and_explicit_choice_overrides_it(self):
        with patch.object(setup_language, "detect_language", return_value="ru"):
            self.assertEqual(setup_language.choose_language(input_fn=lambda _: ""), "ru")
            self.assertEqual(setup_language.choose_language(input_fn=lambda _: "1"), "en")
            self.assertEqual(setup_language.choose_language(language="en", input_fn=lambda _: self.fail("prompt")), "en")

    def test_invalid_choice_is_reprompted(self):
        choices = iter(("invalid", "2"))
        with patch.object(setup_language, "detect_language", return_value="en"), redirect_stdout(io.StringIO()):
            self.assertEqual(setup_language.choose_language(input_fn=lambda _: next(choices)), "ru")

    def test_noninteractive_setup_never_selects_language(self):
        with patch.object(guided_setup, "choose_language") as choose:
            self.assertEqual(guided_setup.setup("/unused", interactive=False)["status"], "pending_owner_interaction")
        choose.assert_not_called()

    def test_github_instructions_explain_correct_app_type_in_both_languages(self):
        for language, phrase in (("en", "Use an OAuth App"), ("ru", "Нужен OAuth App")):
            output = io.StringIO()
            with redirect_stdout(output):
                setup_github_oauth.guide("https://mac.example.com", None, language)
            self.assertIn(phrase, output.getvalue())
            self.assertIn("Client Secret", output.getvalue())
            self.assertIn("https://mac.example.com/auth/callback", output.getvalue())
            self.assertEqual(any("а" <= c <= "я" for c in output.getvalue()), language == "ru")

    def test_selected_language_reaches_gui_and_network_without_another_choice(self):
        with patch.object(guided_setup, "gui_permissions", return_value=True) as gui, \
             patch.object(guided_setup, "guided_network", return_value={"status": "manual_setup_required"}) as network, \
             patch.object(guided_setup, "choose_language") as choose:
            guided_setup._setup_locked(Path("/unused"), language="en")
        self.assertEqual(gui.call_args.kwargs["language"], "en")
        self.assertEqual(network.call_args.kwargs["language"], "en")
        choose.assert_not_called()

    def test_russian_oauth_keeps_yes_consent_and_hidden_secret_input(self):
        answers = iter(("YES", "Ov23abc00000test"))
        prompts = []
        output = io.StringIO()
        def answer(prompt):
            prompts.append(prompt)
            return next(answers)
        def secret(prompt):
            prompts.append(prompt)
            return "secret-value-" + "x" * 30
        with patch.object(setup_github_oauth, "destination", return_value=Path("/missing/config")), \
             patch.object(setup_github_oauth, "github_account", return_value=("owner", "123", "authenticated_github_cli")), \
             patch.object(setup_github_oauth, "save_new_config") as save, redirect_stdout(output):
            result = setup_github_oauth.configure(Path("/unused"), "https://mac.example.com", None,
                                                  language="ru", input_fn=answer, secret_fn=secret)
        self.assertIn("Введите YES", prompts[0])
        self.assertIn("ввод скрыт", prompts[-1])
        self.assertEqual(result["status"], "configured")
        self.assertNotIn("secret-value-", output.getvalue() + str(result))
        self.assertEqual(save.call_args.args[1]["github_allowed_ids"], ["123"])

    def test_oauth_configure_rejects_non_tty_before_language_or_secrets(self):
        with patch.object(setup_github_oauth.sys.stdin, "isatty", return_value=False), \
             patch.object(setup_github_oauth, "choose_language") as choose, \
             patch.object(setup_github_oauth, "configure") as configure:
            with self.assertRaisesRegex(RuntimeError, "Interactive Terminal"):
                setup_github_oauth.main(["--configure", "--public-url", "https://mac.example.com"])
        choose.assert_not_called()
        configure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
