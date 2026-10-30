"""Read-only guided network selection for the owner-led installer."""
from __future__ import annotations

import io
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import tempfile
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import setup_network


ROOT = Path('/example')
CLI = '/Applications/Tailscale.app/Contents/MacOS/Tailscale'


def preflight(*, ips=None, external='8.8.8.8'):
    return {
        'local_addresses': {'ipv4': ips or ['192.168.1.4'], 'ipv6': []},
        'locally_global_ip_candidates': [],
        'external_ipv4': {'address': external, 'type': 'ipv4'},
        'external_ipv6': {'error': 'URLError'},
    }


def publication(host='mac.tailnet.ts.net'):
    target = host + ':443'
    return {'TCP': {'443': {'HTTPS': True}},
            'Web': {target: {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:3201'}}}},
            'AllowFunnel': {target: True}}


def connected():
    return {'installed': True, 'logged_in': True, 'backend_state': 'Running',
            'device_dns_name': 'mac.tailnet.ts.net', 'cli_path': CLI,
            'tailscale_ips': ['100.80.1.2']}


class NetworkWizardTests(unittest.TestCase):
    def invoke(self, answers, **kwargs):
        prompts = []
        values = iter(answers)
        def answer(prompt):
            prompts.append(prompt)
            return next(values)
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            result = setup_network.guided_network(ROOT, input_fn=answer, **kwargs)
        return result, output.getvalue(), prompts

    def test_direct_https_asks_owner_even_when_public_echo_matches(self):
        data = preflight(ips=['8.8.8.8'])
        with patch.object(setup_network, 'inspect', return_value=data) as inspect, \
             patch.object(setup_network, 'tailscale_state', side_effect=AssertionError('Tailscale changed')), \
             patch.object(setup_network, 'run', side_effect=AssertionError('network changed')):
            result, output, prompts = self.invoke(['yes', 'https://control.example.com'])
        inspect.assert_called_once_with(network=True)
        self.assertIn('белый', prompts[0].lower())
        self.assertEqual(result['route'], 'direct_https')
        self.assertEqual(result['status'], 'ready_for_oauth')
        self.assertEqual(result['public_url'], 'https://control.example.com')
        self.assertEqual(result['incoming_reachable'], 'not_tested')
        self.assertFalse(result['external_connectivity_verified'])
        self.assertIn('не доказывает', output)
        self.assertIn('TCP 443', output)
        self.assertIn('127.0.0.1:3201', output)
        self.assertIn('Не пробрасывайте TCP 3201', output)
        self.assertIn('сертификат', output)
        for path in ('/mcp', '/.well-known/', '/auth/callback'):
            self.assertIn(path, output)
        self.assertIn('HTTP-01', output)

    def test_unknown_white_ip_uses_existing_tailscale_without_changes(self):
        data = preflight(ips=['192.168.1.4', '100.80.1.2'])
        status = subprocess.CompletedProcess([], 0, json.dumps(publication()), '')
        with patch.object(setup_network, 'inspect', return_value=data), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, 'run', return_value=status) as run:
            result, output, _ = self.invoke(['unknown'])
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [[CLI, 'funnel', 'status', '--json'], [CLI, 'serve', 'status', '--json']])
        self.assertEqual(result['route'], 'tailscale_funnel')
        self.assertEqual(result['status'], 'ready_for_oauth')
        self.assertEqual(result['public_url'], 'https://mac.tailnet.ts.net')
        self.assertTrue(result['tailscale']['interface_verified'])
        self.assertEqual(result['publication_state']['status'], 'existing_matching')
        self.assertFalse(result['publication_performed'])
        self.assertIn('существующ', output.lower())

    def test_manual_install_confirmation_rechecks_connection_and_interface(self):
        absent = {'installed': False, 'logged_in': False}
        states = [absent, connected()]
        status = subprocess.CompletedProcess([], 0, 'null', '')
        with patch.object(setup_network, 'inspect', side_effect=[preflight(), preflight(ips=['100.80.1.2'])]) as inspect, \
             patch.object(setup_network, 'tailscale_state', side_effect=states) as state, \
             patch.object(setup_network, 'run', return_value=status) as run:
            result, output, prompts = self.invoke(['no', 'READY'])
        self.assertEqual(state.call_count, 2)
        self.assertEqual(inspect.call_count, 2)
        self.assertEqual(inspect.call_args_list[1].kwargs, {'network': False})
        self.assertIn('https://tailscale.com/docs/install/mac', output)
        self.assertIn('учётную запись', output)
        self.assertIn('войдите', output)
        self.assertIn('READY', prompts[-1])
        self.assertEqual(result['status'], 'ready_for_oauth')
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         [[CLI, 'funnel', 'status', '--json'], [CLI, 'serve', 'status', '--json']])

    def test_owner_can_defer_manual_install_without_any_command(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()), \
             patch.object(setup_network, 'tailscale_state', return_value={'installed': False, 'logged_in': False}), \
             patch.object(setup_network, 'run', side_effect=AssertionError('unexpected command')):
            result, _, _ = self.invoke(['no', 'later'])
        self.assertEqual(result['status'], 'manual_setup_required')
        self.assertNotIn('public_url', result)
        self.assertFalse(result['publication_performed'])

    def test_running_backend_without_local_interface_does_not_pass(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, 'run', side_effect=AssertionError('no interface')):
            result, output, _ = self.invoke(['unknown', 'READY', ''])
        self.assertEqual(result['status'], 'manual_setup_required')
        self.assertFalse(result['tailscale']['interface_verified'])
        self.assertIn('интерфейс', output.lower())

    def test_cgnat_signal_is_not_a_claim_of_isp_nat(self):
        with patch.object(setup_network, 'inspect', return_value=preflight(ips=['100.80.1.2'])), \
             patch.object(setup_network, 'tailscale_state', return_value={'installed': False, 'logged_in': False}):
            result, output, _ = self.invoke(['unknown', 'later'])
        self.assertTrue(result['ip_signal']['shared_ipv4_present'])
        self.assertIn('VPN', output)
        self.assertIn('не позволяют', output)
        self.assertEqual(result['incoming_reachable'], 'not_tested')

    def test_invalid_owner_answer_and_origin_are_reprompted(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()):
            result, output, prompts = self.invoke([
                'maybe', 'yes', 'http://control.example.com',
                'https://control.example.com:3201', 'https://8.8.8.8',
                'https://control.example.com',
            ])
        self.assertEqual(len(prompts), 6)
        self.assertEqual(result['public_url'], 'https://control.example.com')
        self.assertIn('HTTPS-домен', output)

    def test_guided_cli_dispatches_new_flow(self):
        with patch.object(setup_network.sys, 'argv', ['setup_network.py', '--guided', '--language', 'en']), \
             patch.object(setup_network, 'guided_network', return_value={'status': 'ready_for_oauth'}) as guided, \
             patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(setup_network.main(), 0)
        guided.assert_called_once_with(setup_network.DEFAULT_ROOT, network=True, language='en')

    def test_tailscale_state_includes_interface_addresses(self):
        payload = {'BackendState': 'Running', 'Self': {'DNSName': 'mac.tailnet.ts.net.',
                                                     'TailscaleIPs': ['100.80.1.2']}}
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'run', side_effect=[
                 subprocess.CompletedProcess([], 0, '1.0\n', ''),
                 subprocess.CompletedProcess([], 0, json.dumps(payload), ''),
             ]):
            result = setup_network.tailscale_state()
        self.assertEqual(result['tailscale_ips'], ['100.80.1.2'])


    def test_publication_state_rejects_conflicting_or_unreadable_configuration(self):
        examples = [
            'not json',
            json.dumps({'TCP': {'3201': {'TCPForward': '127.0.0.1:3201'}}}),
            json.dumps({**publication(), 'Foreground': {'session': publication()}}),
            json.dumps({**publication(), 'Web': {'other.ts.net:443': {}}}),
        ]
        for raw in examples:
            with self.subTest(raw=raw), patch.object(setup_network, 'run', return_value=
                    subprocess.CompletedProcess([], 0, raw, '')):
                result = setup_network.publication_state(CLI, 'mac.tailnet.ts.net')
                self.assertIn(result['status'], ('conflict', 'unreadable'))

    def test_publication_state_rejects_funnel_and_serve_disagreement(self):
        with patch.object(setup_network, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, 'null', ''),
                subprocess.CompletedProcess([], 0, json.dumps(publication()), ''),
        ]):
            result = setup_network.publication_state(CLI, 'mac.tailnet.ts.net')
        self.assertEqual(result['status'], 'conflict')

    def test_guided_conflict_stops_before_oauth_readiness(self):
        data = preflight(ips=['100.80.1.2'])
        with patch.object(setup_network, 'inspect', return_value=data), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, 'run', return_value=
                          subprocess.CompletedProcess([], 0, '{"Services":{"other":{}}}', '')):
            result, output, _ = self.invoke(['unknown'])
        self.assertEqual(result['status'], 'manual_setup_required')
        self.assertIn('существующ', output.lower())
        self.assertFalse(result['publication_performed'])

    def test_enable_reuses_only_exact_authenticated_existing_publication(self):
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, '_oauth_guard', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}), \
             patch.object(setup_network, 'run', return_value=
                          subprocess.CompletedProcess([], 0, json.dumps(publication()), '')) as run:
            result = setup_network.enable_funnel(ROOT, input_fn=lambda _: self.fail('No mutation consent needed'))
        self.assertEqual(result['status'], 'existing_funnel_reused')
        self.assertEqual(len(run.call_args_list), 2)

    def test_enable_refuses_ambiguous_config_before_requesting_publish(self):
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, '_oauth_guard', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}), \
             patch.object(setup_network, 'run', return_value=
                          subprocess.CompletedProcess([], 0, 'unreadable', '')):
            with self.assertRaisesRegex(RuntimeError, 'существующ|конфигурац'):
                setup_network.enable_funnel(ROOT, input_fn=lambda _: self.fail('Do not ask PUBLISH'))

    def test_enable_requires_matching_postcheck_after_explicit_publish(self):
        results = [
            subprocess.CompletedProcess([], 0, 'null', ''),
            subprocess.CompletedProcess([], 0, 'null', ''),
            subprocess.CompletedProcess([], 0, 'null', ''),
            subprocess.CompletedProcess([], 0, 'null', ''),
            subprocess.CompletedProcess([], 0, '', ''),
            subprocess.CompletedProcess([], 0, json.dumps(publication()), ''),
            subprocess.CompletedProcess([], 0, json.dumps(publication()), ''),
        ]
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, '_oauth_guard', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}), \
             patch.object(setup_network.sys.stdin, 'isatty', return_value=True), \
             patch.object(setup_network, 'run', side_effect=results) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            result = setup_network.enable_funnel(ROOT, input_fn=lambda _: 'PUBLISH')
        self.assertEqual(result['status'], 'funnel_command_succeeded')
        self.assertEqual(run.call_args_list[4].args[0], [CLI, 'funnel', '--bg', '3201'])
        self.assertEqual(len(run.call_args_list), 7)

    def test_enable_does_not_claim_success_when_postcheck_fails(self):
        results = [subprocess.CompletedProcess([], 0, raw, '') for raw in
                   ['null', 'null', 'null', 'null', '', 'null', 'null']]
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, '_oauth_guard', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}), \
             patch.object(setup_network.sys.stdin, 'isatty', return_value=True), \
             patch.object(setup_network, 'run', side_effect=results), \
             patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, 'провер'):
                setup_network.enable_funnel(ROOT, input_fn=lambda _: 'PUBLISH')


    def test_publication_state_rejects_non_boolean_security_flags(self):
        config = publication()
        config['TCP']['443']['HTTPS'] = 1
        config['AllowFunnel']['mac.tailnet.ts.net:443'] = 1
        with patch.object(setup_network, 'run', return_value=
                          subprocess.CompletedProcess([], 0, json.dumps(config), '')):
            result = setup_network.publication_state(CLI, 'mac.tailnet.ts.net')
        self.assertEqual(result['status'], 'conflict')

    def test_enable_rechecks_existing_routes_after_waiting_for_owner(self):
        states = [{'status': 'empty'}, {'status': 'conflict', 'reason': 'Route changed'}]
        with patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'tailscale_state', return_value=connected()), \
             patch.object(setup_network, '_oauth_guard', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}), \
             patch.object(setup_network.sys.stdin, 'isatty', return_value=True), \
             patch.object(setup_network, 'publication_state', side_effect=states), \
             patch.object(setup_network, 'run', side_effect=AssertionError('Do not overwrite changed routes')), \
             patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, 'измен'):
                setup_network.enable_funnel(ROOT, input_fn=lambda _: 'PUBLISH')


    def test_publication_state_rejects_boolean_numeric_disagreement_between_views(self):
        altered = publication()
        altered['AllowFunnel']['mac.tailnet.ts.net:443'] = 1
        with patch.object(setup_network, 'run', side_effect=[
                subprocess.CompletedProcess([], 0, json.dumps(publication()), ''),
                subprocess.CompletedProcess([], 0, json.dumps(altered), ''),
        ]):
            result = setup_network.publication_state(CLI, 'mac.tailnet.ts.net')
        self.assertEqual(result['status'], 'conflict')


    def test_russian_white_ip_answers_choose_the_expected_route(self):
        with patch.object(setup_network, 'inspect', return_value=preflight()):
            result, _, _ = self.invoke(['да', 'https://control.example.com'])
        self.assertEqual(result['route'], 'direct_https')
        for answer in ('нет', 'не знаю'):
            with self.subTest(answer=answer), \
                 patch.object(setup_network, 'inspect', return_value=preflight()), \
                 patch.object(setup_network, 'tailscale_state', return_value={
                     'installed': False, 'logged_in': False}):
                result, output, prompts = self.invoke([answer, 'позже'])
            self.assertEqual(result['route'], 'tailscale_funnel')
            self.assertEqual(result['status'], 'manual_setup_required')
            self.assertIn('READY', prompts[-1])
            self.assertIn('войдите', output)


    def test_ready_can_retry_inside_wizard_and_accepts_russian_confirmation(self):
        states = [{'installed': False, 'logged_in': False}, connected(), connected()]
        with patch.object(setup_network, 'inspect', side_effect=[
                preflight(), preflight(), preflight(ips=['100.80.1.2'])]) as inspect, \
             patch.object(setup_network, 'tailscale_state', side_effect=states) as state, \
             patch.object(setup_network, 'publication_state', return_value={'status': 'empty'}):
            result, output, prompts = self.invoke(['не знаю', 'READY', 'ГОТОВО'])
        self.assertEqual(result['status'], 'ready_for_oauth')
        self.assertEqual(state.call_count, 3)
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(len(prompts), 3)
        self.assertIn('не доказывает доступность', output)

    def test_oauth_must_still_match_owner_and_origin_after_publish_prompt(self):
        configured = {'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}
        changes = [RuntimeError('Анонимный ответ больше не 401'),
                   {**configured, 'public_url': 'https://other.example.com'},
                   {**configured, 'allowed_github_ids': ['999']}]
        for changed in changes:
            with self.subTest(changed=changed), \
                 patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
                 patch.object(setup_network, 'tailscale_state', return_value=connected()), \
                 patch.object(setup_network, '_oauth_guard', side_effect=[configured, changed]), \
                 patch.object(setup_network.sys.stdin, 'isatty', return_value=True), \
                 patch.object(setup_network, 'publication_state', return_value={'status': 'empty'}), \
                 patch.object(setup_network, 'run', side_effect=AssertionError('Do not publish changed auth')), \
                 patch('sys.stdout', new_callable=io.StringIO):
                with self.assertRaises(RuntimeError):
                    setup_network.enable_funnel(ROOT, input_fn=lambda _: 'PUBLISH')


@contextmanager
def loopback_server(*, issuer='https://mac.tailnet.ts.net', redirect=None, oversized=False):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            requests.append(self.path)
            if redirect == self.path:
                self.send_response(302)
                self.send_header('Location', '/redirected')
                self.end_headers()
                return
            if self.path == '/.well-known/oauth-authorization-server':
                body = json.dumps({'issuer': issuer}).encode()
                if oversized:
                    body = b' ' * 65537 + body
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Bearer')
            self.end_headers()
        do_GET = do_POST = handle_request
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class OAuthLoopbackGuardTests(unittest.TestCase):
    def guard(self, port):
        with patch.object(setup_network.urllib.request, '_opener', None), \
             patch.object(setup_network, 'PORT', port), \
             patch.object(setup_network, 'check_oauth', return_value={
                 'public_url': 'https://mac.tailnet.ts.net', 'allowed_github_ids': ['123']}):
            return setup_network._oauth_guard(ROOT)

    def test_guard_checks_local_issuer_and_anonymous_challenge(self):
        with loopback_server() as (port, requests):
            self.guard(port)
        self.assertEqual(requests, ['/.well-known/oauth-authorization-server', '/mcp'])

    def test_fastmcp_metadata_issuer_with_terminal_slash_matches_origin(self):
        # Exact issuer shape returned by FastMCP TestClient for the configured origin.
        with loopback_server(issuer='https://mac.tailnet.ts.net/') as (port, requests):
            report = self.guard(port)
        self.assertEqual(report['public_url'], 'https://mac.tailnet.ts.net')
        self.assertEqual(requests, ['/.well-known/oauth-authorization-server', '/mcp'])

    def test_issuer_normalization_does_not_accept_wrong_types_paths_or_queries(self):
        issuers = [None, 123, ['https://mac.tailnet.ts.net/'],
                   {'url': 'https://mac.tailnet.ts.net/'},
                   'https://mac.tailnet.ts.net/other/',
                   'https://mac.tailnet.ts.net/?redirect=1',
                   'https://mac.tailnet.ts.net.evil.example/']
        for issuer in issuers:
            with self.subTest(issuer=issuer), loopback_server(issuer=issuer) as (port, requests):
                with self.assertRaises(RuntimeError):
                    self.guard(port)
            self.assertNotIn('/mcp', requests)

    def test_guard_rejects_wrong_issuer_and_oversized_metadata(self):
        for options in ({'issuer': 'https://other.example.com'}, {'oversized': True}):
            with self.subTest(options=options), loopback_server(**options) as (port, requests):
                with self.assertRaises(RuntimeError):
                    self.guard(port)
            self.assertNotIn('/mcp', requests)

    def test_guard_never_follows_loopback_metadata_or_mcp_redirects(self):
        for path in ('/.well-known/oauth-authorization-server', '/mcp'):
            with self.subTest(path=path), loopback_server(redirect=path) as (port, requests):
                with self.assertRaises(RuntimeError):
                    self.guard(port)
            self.assertNotIn('/redirected', requests)

    def test_guard_bypasses_environment_http_proxy(self):
        with loopback_server() as (port, requests), loopback_server() as (proxy_port, proxy_requests), \
             patch.dict(setup_network.os.environ, {
                 'HTTP_PROXY': 'http://127.0.0.1:' + str(proxy_port),
                 'http_proxy': 'http://127.0.0.1:' + str(proxy_port),
                 'NO_PROXY': '', 'no_proxy': '',
             }):
            self.guard(port)
        self.assertEqual(proxy_requests, [])
        self.assertEqual(requests, ['/.well-known/oauth-authorization-server', '/mcp'])



class FunnelLifecycleGuardTests(unittest.TestCase):
    def test_no_remote_configuration_needs_no_tailscale_check(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(setup_network, 'tailscale_cli', side_effect=AssertionError('No remote config')):
            report = setup_network.assert_public_route_safe_for_uninstall(Path(temp))
        self.assertEqual(report['status'], 'not_applicable')

    def test_direct_https_configuration_needs_no_tailscale_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/remote_auth.json').touch()
            with patch.object(setup_network, 'check_oauth', return_value={
                    'public_url': 'https://control.example.com'}), \
                 patch.object(setup_network, 'tailscale_cli', side_effect=AssertionError('Direct HTTPS')):
                report = setup_network.assert_public_route_safe_for_uninstall(root)
        self.assertEqual(report['status'], 'not_applicable')

    def test_saved_tailscale_origin_requires_demonstrably_empty_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/remote_auth.json').touch()
            with patch.object(setup_network, 'check_oauth', return_value={
                    'public_url': 'https://mac.tailnet.ts.net'}), \
                 patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
                 patch.object(setup_network, 'publication_state', return_value={'status': 'empty'}) as status, \
                 patch.object(setup_network, 'run', side_effect=AssertionError('No mutation')):
                report = setup_network.assert_public_route_safe_for_uninstall(root)
            status.assert_called_once_with(CLI, 'mac.tailnet.ts.net')
        self.assertEqual(report['status'], 'no_active_routes')

    def test_active_ambiguous_and_unreadable_routes_prevent_service_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/remote_auth.json').touch()
            for status in ('existing_matching', 'conflict', 'unreadable'):
                with self.subTest(status=status), \
                     patch.object(setup_network, 'check_oauth', return_value={
                         'public_url': 'https://mac.tailnet.ts.net'}), \
                     patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
                     patch.object(setup_network, 'publication_state', return_value={'status': status}), \
                     patch.object(setup_network, 'run', side_effect=AssertionError('No mutation')):
                    with self.assertRaisesRegex(RuntimeError, '3201.*вручную|вручную.*3201') as error:
                        setup_network.assert_public_route_safe_for_uninstall(root)
                    self.assertIn('mac.tailnet.ts.net', str(error.exception))
                    self.assertIn('funnel status --json', str(error.exception))
                    self.assertIn('serve status --json', str(error.exception))

    def test_missing_cli_does_not_prove_saved_funnel_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/remote_auth.json').touch()
            with patch.object(setup_network, 'check_oauth', return_value={
                    'public_url': 'https://mac.tailnet.ts.net'}), \
                 patch.object(setup_network, 'tailscale_cli', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'CLI'):
                    setup_network.assert_public_route_safe_for_uninstall(root)

    def test_known_remote_service_without_config_still_requires_empty_routes(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(setup_network, 'tailscale_cli', return_value=CLI), \
             patch.object(setup_network, 'publication_state', return_value={'status': 'empty'}) as status:
            report = setup_network.assert_public_route_safe_for_uninstall(Path(temp), known_remote_service=True)
        status.assert_called_once_with(CLI, '')
        self.assertEqual(report['status'], 'no_active_routes')


    def test_direct_proxy_requires_explicit_disabled_confirmation_for_owned_service(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/remote_auth.json').touch()
            with patch.object(setup_network, 'check_oauth', return_value={
                    'public_url': 'https://control.example.com'}), \
                 patch.object(setup_network.sys.stdin, 'isatty', return_value=True), \
                 patch.object(setup_network, 'run', side_effect=AssertionError('No proxy mutation')), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                result = setup_network.assert_public_route_safe_for_uninstall(
                    root, known_remote_service=True, input_fn=lambda _: 'DISABLED')
            self.assertEqual(result['status'], 'owner_confirmed_proxy_disabled')
            self.assertIn('3201', output.getvalue())
            self.assertIn('443', output.getvalue())

    def test_direct_proxy_refusal_or_noninteractive_terminal_blocks_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'data').mkdir()
            (root / 'data/remote_auth.json').touch()
            for interactive in (False, True):
                with self.subTest(interactive=interactive), \
                     patch.object(setup_network, 'check_oauth', return_value={
                         'public_url': 'https://control.example.com'}), \
                     patch.object(setup_network.sys.stdin, 'isatty', return_value=interactive), \
                     patch.object(setup_network, 'run', side_effect=AssertionError('No proxy mutation')), \
                     patch('sys.stdout', new_callable=io.StringIO):
                    with self.assertRaises(RuntimeError):
                        setup_network.assert_public_route_safe_for_uninstall(
                            root, known_remote_service=True, input_fn=lambda _: 'NO')


if __name__ == '__main__':
    unittest.main()
