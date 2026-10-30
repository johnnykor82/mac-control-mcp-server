"""First-time OAuth onboarding never publishes before owner confirmation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import guided_setup


class FreshOAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / ".mac-control-installer-owned").write_text("owned")
        release = self.root / "releases/installed"
        (release / "bin").mkdir(parents=True)
        (release / "bin/mac-control-stdio-mcp.sh").write_text("test")
        (self.root / "current").symlink_to(release)

    def test_new_account_is_configured_before_start_and_publication(self):
        origin = "https://mac.example.ts.net"
        responses = iter(["", "owner"])
        events = []
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": origin}), \
             patch.object(guided_setup, "oauth_check", side_effect=FileNotFoundError), \
             patch.object(guided_setup, "oauth_guide", side_effect=lambda *a: events.append("guide")), \
             patch.object(guided_setup, "oauth_configure", side_effect=lambda *a, **k: events.append("configure") or {"public_url": origin}) as configure, \
             patch.object(guided_setup, "ensure_remote_service", side_effect=lambda *a: events.append("remote")), \
             patch.object(guided_setup, "verify_local_oauth", side_effect=lambda *a, **kw: events.append("guard")), \
             patch.object(guided_setup, "enable_funnel", side_effect=lambda *a, **k: events.append("funnel") or {"status": "funnel_command_succeeded"}), \
             patch.object(guided_setup, "oauth_probe", side_effect=lambda *a: {"status": "public_oauth_preflight_pass"}):
            result = guided_setup.setup(self.root, input_fn=lambda _: next(responses), interactive=True, language="en")
        self.assertEqual(events, ["guide", "configure", "remote", "guard", "funnel"])
        self.assertEqual(configure.call_args.args[:3], (self.root, origin, "owner"))
        self.assertEqual(result["status"], "pending_chatgpt_connection")

    def test_owner_can_defer_before_entering_oauth_credentials(self):
        with patch.object(guided_setup, "gui_permissions", return_value=True), \
             patch.object(guided_setup, "guided_network", return_value={"status": "ready_for_oauth", "route": "tailscale_funnel", "public_url": "https://mac.example.ts.net"}), \
             patch.object(guided_setup, "oauth_check", side_effect=FileNotFoundError), \
             patch.object(guided_setup, "oauth_guide"), \
             patch.object(guided_setup, "oauth_configure") as configure, \
             patch.object(guided_setup, "ensure_remote_service") as service:
            result = guided_setup.setup(self.root, input_fn=lambda _: "s", interactive=True, language="en")
        self.assertEqual(result["status"], "pending_github_oauth")
        configure.assert_not_called()
        service.assert_not_called()


if __name__ == "__main__":
    unittest.main()
