#!/usr/bin/env python3

import ipaddress
import os
import sqlite3
import subprocess
from datetime import datetime, timezone

DB_FILE = "/opt/dns-access/data/users.db"

def now_utc():
    return datetime.now(timezone.utc)


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def valid_ip(ip):
    if not ip:
        return False

    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def run(command):
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def nft_delete_ip(ip):
    if not valid_ip(ip):
        return False

    family = "dns6" if ":" in ip else "dns4"

    return run(
        [
            "/usr/sbin/nft",
            "delete",
            "element",
            "inet",
            "dnsaccess",
            family,
            "{",
            ip,
            "}",
        ]
    )


def remove_expired_ips(conn):
    now = now_utc().isoformat()

    rows = conn.execute(
        """
        SELECT id, ip4, ip6
        FROM users
        WHERE expires_at <= ?
           OR disabled = 1
        """,
        (now,),
    ).fetchall()

    for row in rows:
        for ip in (row["ip4"], row["ip6"]):
            nft_delete_ip(ip)


def refresh_active_ips(conn):
    now = now_utc()

    rows = conn.execute(
        """
        SELECT ip4, ip6, expires_at
        FROM users
        WHERE disabled = 0
          AND expires_at > ?
        """,
        (now.isoformat(),),
    ).fetchall()

    for row in rows:
        expires_at = datetime.fromisoformat(row["expires_at"])

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        seconds = int((expires_at - now).total_seconds())

        if seconds <= 0:
            continue

        for ip in (row["ip4"], row["ip6"]):
            if not valid_ip(ip):
                continue

            family = "dns6" if ":" in ip else "dns4"

            run(
                [
                    "/usr/sbin/nft",
                    "add",
                    "element",
                    "inet",
                    "dnsaccess",
                    family,
                    "{",
                    ip,
                    "timeout",
                    f"{seconds}s",
                    "}",
                ]
            )


def main():
    if not os.path.exists(DB_FILE):
        return

    conn = get_db()

    try:
        remove_expired_ips(conn)
        refresh_active_ips(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
