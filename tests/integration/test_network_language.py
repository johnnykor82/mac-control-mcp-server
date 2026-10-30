"""Network prompts honor the wizard language while keeping safety checks intact."""
import io
import re
import subprocess
import unittest
from unittest.mock import patch

from scripts import setup_network
from tests.integration.test_network_wizard import CLI, ROOT, connected, preflight


class NetworkLanguageTests(unittest.TestCase):
    def invoke(self, answers, *, language):
        prompts = []
        values = iter(answers)
        def answer(prompt):
            prompts.append(prompt)
            return next(values)
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            result = setup_network.guided_network(ROOT, input_fn=answer, language=language)
        return result, output.getvalue() + ''.join(prompts)

    def test_english_direct_route_reprompts_and_preserves_bilingual_answers(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()):
            result, output = self.invoke(['maybe', 'да', 'http://bad.example', 'https://control.example.com'], language='en')
        self.assertEqual(result['status'], 'ready_for_oauth')
        self.assertEqual(result['route'], 'direct_https')
        self.assertIn('Do you have a public IP', output)
        self.assertIn('Do not forward TCP 3201', output)
        self.assertIn('without a path or credentials', output)
        self.assertIsNone(re.search('[А-Яа-яЁё]', output))

    def test_english_tailscale_manual_setup(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()), \
             patch.object(setup_network, 'tailscale_state', return_value={'installed': False}):
            result, output = self.invoke(['no', ''], language='en')
        self.assertEqual(result['status'], 'manual_setup_required')
        self.assertIn('Create a Tailscale account', output)
        self.assertIn('enter READY', output)
        self.assertIsNone(re.search('[А-Яа-яЁё]', output))

    def test_english_conflict_diagnostic(self):
        with patch.object(setup_network, 'inspect', return_value=preflight(ips=['100.80.1.2'])), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, 'run', return_value=subprocess.CompletedProcess([], 0, '{"Services":{"other":{}}}', '')):
            result, output = self.invoke(['unknown'], language='en')
        self.assertEqual(result['status'], 'manual_setup_required')
        self.assertIn('Existing routes do not exactly match', output)
        self.assertIsNone(re.search('[А-Яа-яЁё]', output))

    def test_english_publication_still_requires_exact_publish_confirmation(self):
        prompts = []
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, '_oauth_guard', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}), \
             patch.object(setup_network, 'publication_state', return_value={'status': 'empty'}), \
             patch.object(setup_network.sys.stdin, 'isatty', return_value=True), \
             patch.object(setup_network, 'run') as run, \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            with self.assertRaisesRegex(RuntimeError, 'owner did not confirm'):
                setup_network.enable_funnel(ROOT, language='en', input_fn=lambda prompt: prompts.append(prompt) or 'publish')
        run.assert_not_called()
        self.assertIn('WARNING', output.getvalue())
        self.assertIn('Enter PUBLISH', prompts[0])
        self.assertIsNone(re.search('[А-Яа-яЁё]', output.getvalue() + prompts[0]))

    def test_russian_still_supported_explicitly(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()):
            result, output = self.invoke(['выход'], language='ru')
        self.assertEqual(result['status'], 'cancelled')
        self.assertIn('Проверка сети завершена', output)
