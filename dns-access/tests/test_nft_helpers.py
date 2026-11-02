import importlib.util
import subprocess
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "app.py"

SPEC = importlib.util.spec_from_file_location(
    "dns_access_nft_app",
    MODULE_PATH,
)
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class NftHelperTests(unittest.TestCase):

    def future_expiry(self):
        return (app.now_utc() + timedelta(hours=1)).isoformat()

    @patch.object(app.subprocess, "run")
    def test_replace_success_does_not_call_add(self, mock_run):
        mock_run.return_value = None

        result = app.nft_add_ip("192.0.2.10", self.future_expiry())

        self.assertTrue(result)
        mock_run.assert_called_once()

        command = mock_run.call_args.args[0]
        self.assertEqual(command[:7], [
            "/usr/sbin/nft",
            "replace",
            "element",
            "inet",
            "dnsaccess",
            "dns4",
            "{",
        ])
        self.assertIn("192.0.2.10", command)
        self.assertIn("timeout", command)

    @patch.object(app.subprocess, "run")
    def test_replace_failure_falls_back_to_add(self, mock_run):
        mock_run.side_effect = [
            subprocess.CalledProcessError(
                1,
                ["nft", "replace"],
                stderr="element does not exist",
            ),
            None,
        ]

        result = app.nft_add_ip("192.0.2.11", self.future_expiry())

        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        self.assertEqual(mock_run.call_args_list[0].args[0][1], "replace")
        self.assertEqual(mock_run.call_args_list[1].args[0][1], "add")

    @patch.object(app.subprocess, "run")
    def test_add_failure_returns_false(self, mock_run):
        mock_run.side_effect = [
            subprocess.CalledProcessError(
                1,
                ["nft", "replace"],
                stderr="replace failed",
            ),
            subprocess.CalledProcessError(
                1,
                ["nft", "add"],
                stderr="add failed",
            ),
        ]

        result = app.nft_add_ip("192.0.2.12", self.future_expiry())

        self.assertFalse(result)
        self.assertEqual(mock_run.call_count, 2)

    @patch.object(app.subprocess, "run")
    def test_ipv6_uses_dns6_set(self, mock_run):
        mock_run.return_value = None

        result = app.nft_add_ip("2001:db8::10", self.future_expiry())

        self.assertTrue(result)
        command = mock_run.call_args.args[0]
        self.assertIn("dns6", command)
        self.assertIn("2001:db8::10", command)

    @patch.object(app.subprocess, "run")
    def test_invalid_ip_does_not_call_nft(self, mock_run):
        result = app.nft_add_ip("not-an-ip", self.future_expiry())

        self.assertFalse(result)
        mock_run.assert_not_called()

    @patch.object(app.subprocess, "run")
    def test_expired_address_does_not_call_nft(self, mock_run):
        expiry = (app.now_utc() - timedelta(minutes=1)).isoformat()

        result = app.nft_add_ip("192.0.2.13", expiry)

        self.assertFalse(result)
        mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
