#!/usr/bin/env python3

import ipaddress
import logging
import os
import sqlite3
import subprocess
from datetime import datetime, timezone

DB_FILE = "/opt/dns-access/data/users.db"

logger = logging.getLogger(__name__)


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


def parse_expiration(value):
    try:
        expires_at = datetime.fromisoformat(value)

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return expires_at
    except (TypeError, ValueError):
        return None


def run(command, log_failure=True):
    try:
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        if log_failure:
            logger.error(
                "nft command failed: %s",
                (exc.stderr or "").strip() or "unknown nftables error",
            )
        return False
    except OSError as exc:
        if log_failure:
            logger.error("nft command could not run: %s", exc)
        return False


def nft_delete_ip(ip):
    if not valid_ip(ip):
        return False

    family = "dns6" if ":" in ip else "dns4"

    return run([
        "/usr/sbin/nft",
        "delete",
        "element",
        "inet",
        "dnsaccess",
        family,
        "{",
        ip,
        "}",
    ])


def nft_add_ip(ip, expires_at):
    if not valid_ip(ip):
        return False

    now = now_utc()
    expiry = parse_expiration(expires_at)

    if expiry is None:
        return False

    timeout = int((expiry - now).total_seconds())

    if timeout <= 0:
        return False

    family = "dns6" if ":" in ip else "dns4"
    element = [
        "element",
        "inet",
        "dnsaccess",
        family,
        "{",
        ip,
        "timeout",
        f"{timeout}s",
        "}",
    ]

    if run(["/usr/sbin/nft", "replace", *element], log_failure=False):
        return True

    return run(["/usr/sbin/nft", "add", *element])


def collect_ip_state(conn):
    now = now_utc()
    rows = conn.execute(
        """
        SELECT ip4, ip6, expires_at, disabled
        FROM users
        """
    ).fetchall()

    active_expirations = {}
    inactive_ips = set()

    for row in rows:
        expiry = parse_expiration(row["expires_at"])
        is_active = (
            row["disabled"] == 0
            and expiry is not None
            and expiry > now
        )

        for ip in (row["ip4"], row["ip6"]):
            if not valid_ip(ip):
                continue

            if is_active:
                previous = active_expirations.get(ip)

                if previous is None or expiry > previous:
                    active_expirations[ip] = expiry
            else:
                inactive_ips.add(ip)

    return active_expirations, inactive_ips


def remove_expired_ips(conn, state=None):
    if state is None:
        state = collect_ip_state(conn)

    active_expirations, inactive_ips = state

    for ip in sorted(inactive_ips - set(active_expirations)):
        if not nft_delete_ip(ip):
            logger.error(
                "Could not remove inactive IP address from nftables: %s",
                ip,
            )


def refresh_active_ips(conn, active_expirations=None):
    if active_expirations is None:
        active_expirations, _ = collect_ip_state(conn)

    for ip, expires_at in sorted(active_expirations.items()):
        if not nft_add_ip(ip, expires_at.isoformat()):
            logger.error(
                "Could not refresh active IP address in nftables: %s",
                ip,
            )


def main():
    if not os.path.exists(DB_FILE):
        return

    conn = get_db()

    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            logger.exception("Could not acquire maintenance database transaction")
            return

        state = collect_ip_state(conn)
        active_expirations, _ = state

        remove_expired_ips(conn, state)
        refresh_active_ips(conn, active_expirations)

        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
