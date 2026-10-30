"""Installation chooses the language before starting its interactive work."""
import unittest
from unittest.mock import patch

from scripts import install_mac_control as installer
from scripts import setup_language


class InstallLanguageTests(unittest.TestCase):
    def test_interactive_install_chooses_before_install_and_passes_selection(self):
        steps = []
        def choose():
            steps.append('language')
            return 'ru'
        def install(*args, **kwargs):
            steps.append('install')
            return {'status': 'installed'}
        with patch.object(installer.sys, 'argv', ['installer', '--install']), \
             patch.object(installer.sys.stdin, 'isatty', return_value=True), \
             patch.object(setup_language, 'choose_language', side_effect=choose), \
             patch.object(installer, 'install', side_effect=install), \
             patch.object(installer, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(installer.main(), 0)
        self.assertEqual(steps, ['language', 'install'])
        self.assertEqual(run.call_args.args[0][-2:], ['--language', 'ru'])

    def test_noninteractive_install_does_not_prompt(self):
        with patch.object(installer.sys, 'argv', ['installer', '--install']), \
             patch.object(installer.sys.stdin, 'isatty', return_value=False), \
             patch.object(setup_language, 'choose_language') as choose, \
             patch.object(installer, 'install', return_value={'status': 'installed'}):
            self.assertEqual(installer.main(), 0)
        choose.assert_not_called()

    def test_explicit_setup_language_is_forwarded(self):
        with patch.object(installer.sys, 'argv', ['installer', '--setup', '--language', 'ru']), \
             patch.object(installer, 'run') as run:
            run.return_value.returncode = 0
            self.assertEqual(installer.main(), 0)
        self.assertEqual(run.call_args.args[0][-2:], ['--language', 'ru'])


    def test_explicit_language_is_forwarded_to_network_and_oauth(self):
        for action in ("--network-guide", "--enable-funnel", "--github-oauth-guide", "--setup-github-oauth"):
            with self.subTest(action=action), \
                 patch.object(installer.sys, 'argv', ['installer', action, '--language', 'ru']), \
                 patch.object(installer, 'run') as run:
                run.return_value.returncode = 0
                self.assertEqual(installer.main(), 0)
                self.assertEqual(run.call_args.args[0][-2:], ['--language', 'ru'])


if __name__ == '__main__':
    unittest.main()
