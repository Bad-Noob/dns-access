import http.client
import importlib.util
import re
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "app.py"

SPEC = importlib.util.spec_from_file_location(
    "dns_access_app",
    MODULE_PATH,
)

app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class JoinSecurityTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app.DB_FILE = str(Path(self.temp_dir.name) / "users.db")

        conn = app.get_db()
        expires_at = (
            app.now_utc() + timedelta(days=2)
        ).isoformat()

        conn.execute(
            """
            INSERT INTO users (
                username,
                token_hash,
                expires_at,
                ip4,
                ip6,
                disabled,
                created_at,
                updated_at,
                link_enc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-user",
                app.hash_token("test-token"),
                expires_at,
                None,
                "2001:db8::10",
                0,
                app.now_utc().isoformat(),
                app.now_utc().isoformat(),
                None,
            ),
        )
        conn.commit()
        conn.close()

        self.server = app.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            app.Handler,
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.server_thread.start()

        self.addCleanup(self.cleanup_server)

        self.nft_add = patch.object(
            app,
            "nft_add_ip",
            return_value=True,
        )
        self.nft_delete = patch.object(
            app,
            "nft_delete_ip",
            return_value=True,
        )

        self.mock_nft_add = self.nft_add.start()
        self.mock_nft_delete = self.nft_delete.start()

        self.addCleanup(self.nft_add.stop)
        self.addCleanup(self.nft_delete.stop)

        self.path = "/join/test-token"

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=3)
        self.temp_dir.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection(
            "127.0.0.1",
            self.server.server_port,
            timeout=5,
        )
        conn.request(
            method,
            path,
            body=body,
            headers=headers or {},
        )
        response = conn.getresponse()
        result = (
            response.status,
            response.getheaders(),
            response.read(),
        )
        conn.close()
        return result

    def get_user(self):
        conn = app.get_db()
        try:
            return conn.execute(
                "SELECT * FROM users WHERE username = ?",
                ("test-user",),
            ).fetchone()
        finally:
            conn.close()

    def test_get_does_not_activate_access(self):
        status, headers, body = self.request(
            "GET",
            self.path,
        )

        self.assertEqual(status, 200)
        self.assertIn(b"Confirm DNS Access", body)
        self.assertTrue(
            any(name.lower() == "set-cookie" for name, value in headers)
        )

        user = self.get_user()
        self.assertIsNone(user["ip4"])
        self.assertEqual(user["ip6"], "2001:db8::10")

        self.mock_nft_add.assert_not_called()
        self.mock_nft_delete.assert_not_called()

    def test_post_without_csrf_cookie_is_rejected(self):
        body = urlencode({"csrf_token": "invalid-token"})

        status, headers, response_body = self.request(
            "POST",
            self.path,
            body,
            {
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        self.assertEqual(status, 403)
        self.assertIn(b"Request Rejected", response_body)
        self.mock_nft_add.assert_not_called()
        self.mock_nft_delete.assert_not_called()

        user = self.get_user()
        self.assertIsNone(user["ip4"])
        self.assertEqual(user["ip6"], "2001:db8::10")

    def test_post_preserves_existing_ipv6_address(self):
        status, headers, body = self.request(
            "GET",
            self.path,
        )

        self.assertEqual(status, 200)

        cookie_header = next(
            value
            for name, value in headers
            if name.lower() == "set-cookie"
        )
        cookie = cookie_header.split(";", 1)[0]

        match = re.search(
            rb'name="csrf_token"\s+value="([^"]+)"',
            body,
        )
        self.assertIsNotNone(match)

        csrf_token = match.group(1).decode("ascii")
        post_body = urlencode({"csrf_token": csrf_token})

        status, headers, response_body = self.request(
            "POST",
            self.path,
            post_body,
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Cookie": cookie,
            },
        )

        self.assertEqual(status, 200)
        self.assertIn(b"Access Activated", response_body)

        user = self.get_user()
        self.assertEqual(user["ip4"], "127.0.0.1")
        self.assertEqual(user["ip6"], "2001:db8::10")

        self.mock_nft_add.assert_called_once()
        self.mock_nft_delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
