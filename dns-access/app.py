#!/usr/bin/env python3

import hashlib
import ipaddress
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote
from html import escape

DB_FILE = "/opt/dns-access/data/users.db"
NGINX_ALLOW_FILE = "/etc/nginx/dns-allow.conf"

HOST = os.getenv("DNS_ACCESS_HOST", "127.0.0.1")
PORT = int(os.getenv("DNS_ACCESS_PORT", "8787"))


def now_utc():
    return datetime.now(timezone.utc)


def get_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            ip4 TEXT,
            ip6 TEXT,
            disabled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            link_enc TEXT
        )
        """
    )

    conn.commit()
    return conn


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_ip(value):
    if not value:
        return False

    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def client_ip(handler):
    forwarded = handler.headers.get("X-Real-IP", "").strip()

    if valid_ip(forwarded):
        return forwarded

    forwarded_for = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()

    if valid_ip(forwarded_for):
        return forwarded_for

    return handler.client_address[0]


def nft_timeout_seconds(expires_at):
    try:
        expires = datetime.fromisoformat(expires_at)

        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        seconds = int((expires - now_utc()).total_seconds())

        if seconds <= 0:
            return 0

        return seconds

    except ValueError:
        return 0


def nft_run(args):
    try:
        subprocess.run(
            ["/usr/sbin/nft", *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def nft_add_ip(ip, expires_at):
    if not valid_ip(ip):
        return False

    timeout = nft_timeout_seconds(expires_at)

    if timeout <= 0:
        return False

    family = "dns6" if ":" in ip else "dns4"

    command = [
        "add",
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

    return nft_run(command)


def nft_delete_ip(ip):
    if not valid_ip(ip):
        return False

    family = "dns6" if ":" in ip else "dns4"

    return nft_run(
        [
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

    lines = [f"allow {ip};" for ip in sorted(ips)]
    lines.append("deny all;")

    os.makedirs(os.path.dirname(NGINX_ALLOW_FILE), exist_ok=True)

    temp_file = NGINX_ALLOW_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")

    os.replace(temp_file, NGINX_ALLOW_FILE)

    try:
        subprocess.run(
            ["/usr/sbin/nginx", "-t"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        subprocess.run(
            ["/usr/bin/systemctl", "reload", "nginx"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def html_page(title, message, success=True):
    status_class = "success" if success else "error"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body {{
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #0f172a;
    color: #e2e8f0;
    font-family: Arial, sans-serif;
}}
.card {{
    width: min(92%, 520px);
    padding: 32px;
    border-radius: 18px;
    background: #1e293b;
    box-shadow: 0 20px 50px rgba(0,0,0,.35);
    text-align: center;
}}
h1 {{
    margin-top: 0;
}}
.success {{
    color: #4ade80;
}}
.error {{
    color: #f87171;
}}
p {{
    line-height: 1.7;
}}
</style>
</head>
<body>
<div class="card">
<h1 class="{status_class}">{title}</h1>
<p>{message}</p>
</div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format_string, *args):
        print(format_string % args)

    def send_html(self, status, body):
        encoded = body.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if not path.startswith("/join/"):
            self.send_html(
                404,
                html_page(
                    "Not Found",
                    "The requested page does not exist.",
                    False,
                ),
            )
            return

        token = unquote(path[len("/join/"):]).strip()

        if not token:
            self.send_html(
                400,
                html_page(
                    "Invalid Link",
                    "The access link is invalid.",
                    False,
                ),
            )
            return

        token_hash = hash_token(token)
        ip = client_ip(self)

        conn = get_db()

        try:
            user = conn.execute(
                """
                SELECT *
                FROM users
                WHERE token_hash = ?
                LIMIT 1
                """,
                (token_hash,),
            ).fetchone()

            if user is None:
                self.send_html(
                    404,
                    html_page(
                        "Invalid Link",
                        "This access link is not valid.",
                        False,
                    ),
                )
                return

            if user["disabled"]:
                self.send_html(
                    403,
                    html_page(
                        "Access Disabled",
                        "This access link has been disabled.",
                        False,
                    ),
                )
                return

            expires_at = datetime.fromisoformat(user["expires_at"])

            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

            if expires_at <= now_utc():
                self.send_html(
                    403,
                    html_page(
                        "Access Expired",
                        "This access link has expired.",
                        False,
                    ),
                )
                return

            old_ip4 = user["ip4"]
            old_ip6 = user["ip6"]

            ip4 = old_ip4
            ip6 = old_ip6

            if ":" in ip:
                ip6 = ip
            else:
                ip4 = ip

            if old_ip4 and old_ip4 != ip4:
                nft_delete_ip(old_ip4)

            if old_ip6 and old_ip6 != ip6:
                nft_delete_ip(old_ip6)

            if not nft_add_ip(ip, user["expires_at"]):
                self.send_html(
                    500,
                    html_page(
                        "Access Error",
                        "The server could not update DNS access.",
                        False,
                    ),
                )
                return

            updated_at = now_utc().isoformat()

            conn.execute(
                """
                UPDATE users
                SET ip4 = ?,
                    ip6 = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    ip4,
                    ip6,
                    updated_at,
                    user["id"],
                ),
            )

            conn.commit()

            rebuild_nginx_allowlist(conn)

            self.send_html(
                200,
                html_page(
                    "Access Activated",
                    f"DNS access has been activated for this connection.<br><br>"
                    f"Registered IP: <strong>{ip}</strong><br><br>"
                    f"Expires: <strong>{user['expires_at']}</strong>",
                    True,
                ),
            )

        finally:
            conn.close()


def main():
    conn = get_db()
    rebuild_nginx_allowlist(conn)
    conn.close()

    server = ThreadingHTTPServer((HOST, PORT), Handler)

    print(f"DNS Access Service listening on {HOST}:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
