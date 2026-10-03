#!/usr/bin/env python3

import os
import sqlite3
import subprocess
from datetime import datetime, timezone


DB_FILE = "/opt/dns-access/data/users.db"
NGINX_ALLOW_FILE = "/etc/nginx/dns-allow.conf"


def now_utc():
    return datetime.now(timezone.utc)


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def valid_ip(ip):
    if not ip:
        return False

    import ipaddress

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


def rebuild_nginx_allowlist(conn):
    rows = conn.execute(
        """
        SELECT ip4, ip6
        FROM users
        WHERE disabled = 0
          AND expires_at > ?
        """,
        (now_utc().isoformat(),),
    ).fetchall()

    ips = set()

    for row in rows:
        if valid_ip(row["ip4"]):
            ips.add(row["ip4"])

        if valid_ip(row["ip6"]):
            ips.add(row["ip6"])

    lines = [
        f"allow {ip};"
        for ip in sorted(ips)
    ]

    lines.append("deny all;")

    os.makedirs(
        os.path.dirname(NGINX_ALLOW_FILE),
        exist_ok=True,
    )

    temp_file = NGINX_ALLOW_FILE + ".tmp"

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as f:
        f.write("\n".join(lines))
        f.write("\n")

    os.replace(
        temp_file,
        NGINX_ALLOW_FILE,
    )

    run(
        [
            "/usr/sbin/nginx",
            "-t",
        ]
    )

    run(
        [
            "/usr/bin/systemctl",
            "reload",
            "nginx",
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

        for ip in (
            row["ip4"],
            row["ip6"],
        ):

            if not valid_ip(ip):
                continue

            family = (
                "dns6"
                if ":" in ip
                else "dns4"
            )

            run(
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


def main():

    if not os.path.exists(DB_FILE):
        return

    conn = get_db()

    remove_expired_ips(conn)

    rebuild_nginx_allowlist(conn)

    conn.close()


if __name__ == "__main__":
    main()
