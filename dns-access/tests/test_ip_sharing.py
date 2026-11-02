import importlib.util
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "app.py"
SPEC = importlib.util.spec_from_file_location("dns_access_ip_sharing", MODULE_PATH)
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class IpSharingTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_db_file = app.DB_FILE
        app.DB_FILE = str(Path(self.temp_dir.name) / "users.db")

        self.conn = app.get_db()

        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.conn.close()
        app.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def add_user(self, username, ip4, ip6, expires_at, disabled=0):
        now = app.now_utc().isoformat()
        self.conn.execute(
            """
            INSERT INTO users (
                username, token_hash, expires_at, ip4, ip6,
                disabled, created_at, updated_at, link_enc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                app.hash_token(username),
                expires_at,
                ip4,
                ip6,
                disabled,
                now,
                now,
                None,
            ),
        )
        self.conn.commit()

        return self.conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,),
        ).fetchone()["id"]

    def test_shared_ip_uses_latest_active_expiration(self):
        first_expiry = app.now_utc() + timedelta(hours=2)
        second_expiry = app.now_utc() + timedelta(hours=5)

        self.add_user("first", "192.0.2.20", None, first_expiry.isoformat())
        self.add_user("second", None, "192.0.2.20", second_expiry.isoformat())

        result = app.nft_expiry_for_ip(self.conn, "192.0.2.20")

        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            app.datetime.fromisoformat(result).timestamp(),
            second_expiry.timestamp(),
            delta=2,
        )

    def test_disabled_user_does_not_extend_shared_ip(self):
        active_expiry = app.now_utc() + timedelta(hours=3)
        disabled_expiry = app.now_utc() + timedelta(days=2)

        self.add_user("active", "192.0.2.21", None, active_expiry.isoformat())
        self.add_user(
            "disabled",
            None,
            "192.0.2.21",
            disabled_expiry.isoformat(),
            disabled=1,
        )

        result = app.nft_expiry_for_ip(self.conn, "192.0.2.21")

        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            app.datetime.fromisoformat(result).timestamp(),
            active_expiry.timestamp(),
            delta=2,
        )

    def test_excluded_user_can_be_included_with_new_expiration(self):
        old_expiry = app.now_utc() + timedelta(hours=1)
        new_expiry = app.now_utc() + timedelta(hours=4)

        user_id = self.add_user(
            "moving",
            "192.0.2.22",
            None,
            old_expiry.isoformat(),
        )

        result = app.nft_expiry_for_ip(
            self.conn,
            "192.0.2.22",
            exclude_user_id=user_id,
            include_expiry=new_expiry.isoformat(),
        )

        self.assertIsNotNone(result)
        self.assertAlmostEqual(
            app.datetime.fromisoformat(result).timestamp(),
            new_expiry.timestamp(),
            delta=2,
        )

    def test_unused_ip_has_no_expiration(self):
        result = app.nft_expiry_for_ip(self.conn, "192.0.2.23")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
