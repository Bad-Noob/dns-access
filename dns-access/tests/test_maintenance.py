import importlib.util
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "maintenance.py"
SPEC = importlib.util.spec_from_file_location("dns_access_maintenance", MODULE_PATH)
maintenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(maintenance)


class MaintenanceTests(unittest.TestCase):

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE users (
                ip4 TEXT,
                ip6 TEXT,
                expires_at TEXT,
                disabled INTEGER
            )
            """
        )

        self.now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        self.time_patch = patch.object(
            maintenance,
            "now_utc",
            return_value=self.now,
        )
        self.time_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.conn.close)

    def add_user(self, ip4, ip6, expires_at, disabled=0):
        self.conn.execute(
            """
            INSERT INTO users (ip4, ip6, expires_at, disabled)
            VALUES (?, ?, ?, ?)
            """,
            (ip4, ip6, expires_at.isoformat(), disabled),
        )
        self.conn.commit()

    def test_shared_ip_uses_latest_active_expiration(self):
        self.add_user(
            "192.0.2.30",
            None,
            self.now + timedelta(hours=2),
        )
        self.add_user(
            None,
            "192.0.2.30",
            self.now + timedelta(hours=5),
        )

        active, inactive = maintenance.collect_ip_state(self.conn)

        self.assertEqual(
            active["192.0.2.30"],
            self.now + timedelta(hours=5),
        )
        self.assertNotIn("192.0.2.30", inactive)

    def test_expired_user_does_not_cause_shared_ip_deletion(self):
        self.add_user(
            "192.0.2.31",
            None,
            self.now - timedelta(minutes=1),
        )
        self.add_user(
            None,
            "192.0.2.31",
            self.now + timedelta(hours=3),
        )

        with patch.object(maintenance, "nft_delete_ip") as delete_ip:
            maintenance.remove_expired_ips(self.conn)

        delete_ip.assert_not_called()

    def test_expired_unshared_ip_is_deleted(self):
        self.add_user(
            "192.0.2.32",
            None,
            self.now - timedelta(minutes=1),
        )

        with patch.object(
            maintenance,
            "nft_delete_ip",
            return_value=True,
        ) as delete_ip:
            maintenance.remove_expired_ips(self.conn)

        delete_ip.assert_called_once_with("192.0.2.32")

    def test_disabled_user_ip_is_deleted_when_not_shared(self):
        self.add_user(
            None,
            "2001:db8::32",
            self.now + timedelta(days=1),
            disabled=1,
        )

        with patch.object(
            maintenance,
            "nft_delete_ip",
            return_value=True,
        ) as delete_ip:
            maintenance.remove_expired_ips(self.conn)

        delete_ip.assert_called_once_with("2001:db8::32")

    def test_active_ip_is_refreshed_once_with_latest_expiration(self):
        latest_expiry = self.now + timedelta(hours=6)

        self.add_user(
            "192.0.2.33",
            None,
            self.now + timedelta(hours=2),
        )
        self.add_user(
            None,
            "192.0.2.33",
            latest_expiry,
        )

        with patch.object(
            maintenance,
            "nft_add_ip",
            return_value=True,
        ) as add_ip:
            maintenance.refresh_active_ips(self.conn)

        add_ip.assert_called_once_with(
            "192.0.2.33",
            latest_expiry.isoformat(),
        )

    def test_invalid_expiration_is_not_active(self):
        self.conn.execute(
            """
            INSERT INTO users (ip4, ip6, expires_at, disabled)
            VALUES (?, ?, ?, ?)
            """,
            ("192.0.2.34", None, "invalid-date", 0),
        )
        self.conn.commit()

        active, inactive = maintenance.collect_ip_state(self.conn)

        self.assertNotIn("192.0.2.34", active)
        self.assertIn("192.0.2.34", inactive)


if __name__ == "__main__":
    unittest.main()
