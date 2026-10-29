"""Offline release tooling tests; no network or machine mutations."""
from __future__ import annotations

import io
import unittest
from unittest import mock

from scripts import release_audit, release_preflight


class PreflightTests(unittest.TestCase):
    def test_inspection_does_not_require_network(self):
        with mock.patch.object(release_preflight, "public_address",
                               side_effect=AssertionError("network called")):
            report = release_preflight.inspect(network=False)
        self.assertEqual(report["external_ipv4"]["status"], "not_checked")
        self.assertEqual(report["incoming_reachable"], "not_tested")

    def test_public_address_parses_real_ip_not_html(self):
        response = io.BytesIO(b"203.0.113.7")
        with mock.patch.object(release_preflight.urllib.request, "urlopen",
                               return_value=response):
            report = release_preflight.public_address("https://example.invalid")
        self.assertEqual(report["address"], "203.0.113.7")
        self.assertEqual(report["type"], "ipv4")

    def test_interface_addresses_filter_loopback_and_link_local(self):
        mocked = ("lo0: flags\n    inet 127.0.0.1 netmask\n"
                  "en0: flags\n    inet 192.168.1.5 netmask\n"
                  "en1: flags\n    inet6 fe80::12%en1 prefixlen\n")
        with mock.patch.object(release_preflight, "output", return_value=mocked):
            result = release_preflight.addresses()
        self.assertEqual(result["ipv4"], ["192.168.1.5"])
        self.assertEqual(result["ipv6"], [])


class ReleaseAuditTests(unittest.TestCase):
    def test_detector_matches_fabricated_token(self):
        fake = b"gh" + b"p_" + b"X" * 26
        patterns = {name: regex for name, _, regex in release_audit.PATTERNS}
        self.assertTrue(patterns["github_token"].search(fake))

    def test_detector_matches_fake_private_key_header(self):
        fake = b"-----BEGIN " + b"PRIVATE " + b"KEY-----"
        patterns = {name: regex for name, _, regex in release_audit.PATTERNS}
        self.assertTrue(patterns["private_key"].search(fake))


if __name__ == "__main__":
    unittest.main()
