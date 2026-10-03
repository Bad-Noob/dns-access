#!/usr/bin/env python3

import hashlib
import html
import ipaddress
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse


CONFIG_FILE = "/etc/dns-access.conf"
DB_FILE = "/opt/dns-access/data/users.db"

NGINX_ALLOW_FILE = "/etc/nginx/dns-allow.conf"
NGINX_BIN = "/usr/sbin/nginx"

HOST = "127.0.0.1"
PORT = 8787


def load_config():
    config = {}

    if not os.path.exists(CONFIG_FILE):
        return config

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if (
                not line
                or line.startswith("#")
                or "=" not in line
            ):
                continue

            key, value = line.split("=", 1)

            config[key.strip()] = (
                value.strip()
                .strip('"')
                .strip("'")
            )

    return config


CONFIG = load_config()

DOMAIN = CONFIG.get("DOMAIN", "")
SERVER_IP = CONFIG.get("SERVER_IP", "")


def now_utc():
    return datetime.now(timezone.utc)


def get_db():
    os.makedirs(
        os.path.dirname(DB_FILE),
        exist_ok=True,
    )

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
            updated_at TEXT,
            link_enc TEXT
        )
        """
    )

    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    }

    if "link_enc" not in columns:
        conn.execute(
            """
            ALTER TABLE users
            ADD COLUMN link_enc TEXT
            """
        )

    conn.commit()

    return conn


def validate_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def run_command(command):
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


def nft_add_ip(ip, seconds):
    if not validate_ip(ip):
        return False

    family = (
        "dns6"
        if ":" in ip
        else "dns4"
    )

    timeout = max(
        1,
        int(seconds),
    )

    return run_command(
        [
            "nft",
            "add",
            "element",
            "inet",
            "dnsaccess",
            family,
            "{",
            f"{ip}",
            "timeout",
            f"{timeout}s",
            "}",
        ]
    )


def nft_delete_ip(ip):
    if not validate_ip(ip):
        return False

    family = (
        "dns6"
        if ":" in ip
        else "dns4"
    )

    return run_command(
        [
            "nft",
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


def reload_nginx():
    if not os.path.exists(NGINX_BIN):
        return False

    return run_command(
        [
            NGINX_BIN,
            "-s",
            "reload",
        ]
    )


def rebuild_nginx_allowlist():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT ip4, ip6
        FROM users
        WHERE disabled = 0
          AND expires_at > ?
        """,
        (
            now_utc().isoformat(),
        ),
    ).fetchall()

    conn.close()

    ips = set()

    for row in rows:

        if row["ip4"]:
            ips.add(row["ip4"])

        if row["ip6"]:
            ips.add(row["ip6"])

    lines = []

    for ip in sorted(ips):

        if validate_ip(ip):
            lines.append(
                f"allow {ip};"
            )

    lines.append(
        "deny all;"
    )

    os.makedirs(
        os.path.dirname(
            NGINX_ALLOW_FILE
        ),
        exist_ok=True,
    )

    temp_file = (
        NGINX_ALLOW_FILE
        + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as f:

        f.write(
            "\n".join(lines)
        )

        f.write("\n")

    os.replace(
        temp_file,
        NGINX_ALLOW_FILE,
    )

    reload_nginx()


def parse_expiry(value):
    try:

        expires = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

        if expires.tzinfo is None:
            expires = expires.replace(
                tzinfo=timezone.utc
            )

        return expires

    except ValueError:
        return None


def register_ip(
    user_id,
    client_ip,
):
    if not validate_ip(client_ip):
        return False

    conn = get_db()

    row = conn.execute(
        """
        SELECT
            expires_at,
            disabled,
            ip4,
            ip6
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    if not row:
        conn.close()
        return False

    if row["disabled"]:
        conn.close()
        return False

    expires = parse_expiry(
        row["expires_at"]
    )

    if not expires:
        conn.close()
        return False

    remaining = int(
        (
            expires - now_utc()
        ).total_seconds()
    )

    if remaining <= 0:
        conn.close()
        return False

    old_ip = None

    if ":" in client_ip:

        old_ip = row["ip6"]

        conn.execute(
            """
            UPDATE users
            SET
                ip6 = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                client_ip,
                now_utc().isoformat(),
                user_id,
            ),
        )

    else:

        old_ip = row["ip4"]

        conn.execute(
            """
            UPDATE users
            SET
                ip4 = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                client_ip,
                now_utc().isoformat(),
                user_id,
            ),
        )

    conn.commit()
    conn.close()

    if old_ip and old_ip != client_ip:
        nft_delete_ip(old_ip)

    nft_add_ip(
        client_ip,
        remaining,
    )

    rebuild_nginx_allowlist()

    return True


def page(
    title,
    body,
):
    return f"""<!doctype html>
<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width,initial-scale=1">

<title>{html.escape(title)}</title>

<style>

:root {{
    --bg:#f1f5f9;
    --card:#ffffff;
    --text:#0f172a;
    --muted:#64748b;
    --border:#e2e8f0;
    --primary:#6366f1;
    --green:#16a34a;
    --shadow:0 20px 50px rgba(15,23,42,.10);
}}

[data-theme="dark"] {{
    --bg:#0b1120;
    --card:#111827;
    --text:#f8fafc;
    --muted:#94a3b8;
    --border:#263244;
    --primary:#818cf8;
    --green:#4ade80;
    --shadow:0 20px 55px rgba(0,0,0,.40);
}}

* {{
    box-sizing:border-box;
}}

body {{
    margin:0;
    min-height:100vh;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:20px;
    background:var(--bg);
    color:var(--text);
    font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}}

.card {{
    width:100%;
    max-width:520px;
    background:var(--card);
    border:1px solid var(--border);
    border-radius:26px;
    padding:30px;
    box-shadow:var(--shadow);
}}

.icon {{
    width:58px;
    height:58px;
    margin:0 auto 18px;
    display:grid;
    place-items:center;
    border-radius:50%;
    background:rgba(99,102,241,.12);
    color:var(--primary);
    font-size:28px;
    font-weight:800;
}}

h1 {{
    margin:0;
    text-align:center;
    font-size:25px;
}}

.subtitle {{
    margin:10px 0 22px;
    text-align:center;
    color:var(--muted);
    line-height:1.6;
}}

.status {{
    display:flex;
    align-items:center;
    justify-content:center;
    gap:8px;
    padding:11px;
    border-radius:12px;
    background:rgba(22,163,74,.10);
    color:var(--green);
    font-weight:700;
    font-size:13px;
}}

.dot {{
    width:8px;
    height:8px;
    border-radius:50%;
    background:currentColor;
}}

.info {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:10px;
    margin-top:18px;
}}

.box {{
    padding:14px;
    border:1px solid var(--border);
    border-radius:15px;
}}

.label {{
    display:block;
    margin-bottom:7px;
    color:var(--muted);
    font-size:11px;
    font-weight:700;
    text-transform:uppercase;
    letter-spacing:.04em;
}}

.value {{
    font-size:14px;
    font-weight:700;
    word-break:break-word;
}}

.dns {{
    margin-top:18px;
}}

.dns-item {{
    padding:14px;
    margin-top:8px;
    border:1px solid var(--border);
    border-radius:15px;
}}

.dns-value {{
    font-family:
        ui-monospace,
        SFMono-Regular,
        Menlo,
        monospace;
    font-size:13px;
    font-weight:700;
    word-break:break-all;
}}

.note {{
    margin:18px 0 0;
    color:var(--muted);
    font-size:12px;
    line-height:1.7;
    text-align:center;
}}

.footer {{
    margin-top:22px;
    text-align:center;
    color:var(--muted);
    font-size:11px;
}}

@media (max-width:520px) {{

    .info {{
        grid-template-columns:1fr;
    }}

    .card {{
        padding:22px;
    }}
}}

</style>

</head>

<body>

<div class="card">

{body}

</div>

<script>

if (
    localStorage.getItem("dns-theme")
    === "dark"
) {{
    document.documentElement
        .setAttribute(
            "data-theme",
            "dark"
        );
}}

</script>

</body>

</html>
"""


class Handler(BaseHTTPRequestHandler):

    def log_message(
        self,
        fmt,
        *args,
    ):
        print(
            "%s - request received"
            % self.client_address[0]
        )

    def send_html(
        self,
        status,
        content,
    ):
        data = content.encode(
            "utf-8"
        )

        self.send_response(status)

        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8",
        )

        self.send_header(
            "Content-Length",
            str(len(data)),
        )

        self.send_header(
            "Cache-Control",
            "no-store",
        )

        self.end_headers()

        self.wfile.write(data)

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        path = parsed.path

        if not path.startswith(
            "/join/"
        ):

            self.send_html(
                404,
                page(
                    "Not Found",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Page Not Found
                    </h1>

                    <p class="subtitle">
                        The requested page does not exist.
                    </p>
                    """,
                ),
            )

            return

        token = path[
            len("/join/"):
        ]

        if (
            not token
            or len(token) < 20
        ):

            self.send_html(
                403,
                page(
                    "Invalid Link",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Invalid Access Link
                    </h1>

                    <p class="subtitle">
                        This access link is invalid or incomplete.
                    </p>
                    """,
                ),
            )

            return

        token_hash = hashlib.sha256(
            token.encode()
        ).hexdigest()

        conn = get_db()

        row = conn.execute(
            """
            SELECT
                id,
                username,
                expires_at,
                disabled
            FROM users
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        conn.close()

        if not row:

            self.send_html(
                403,
                page(
                    "Invalid Link",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Invalid Access Link
                    </h1>

                    <p class="subtitle">
                        This access link is invalid or no longer exists.
                    </p>
                    """,
                ),
            )

            return

        if row["disabled"]:

            self.send_html(
                403,
                page(
                    "Access Disabled",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Access Disabled
                    </h1>

                    <p class="subtitle">
                        This account has been disabled.
                    </p>
                    """,
                ),
            )

            return

        expires = parse_expiry(
            row["expires_at"]
        )

        if not expires:

            self.send_html(
                500,
                page(
                    "Server Error",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Server Error
                    </h1>

                    <p class="subtitle">
                        The account expiry information is invalid.
                    </p>
                    """,
                ),
            )

            return

        if expires <= now_utc():

            self.send_html(
                403,
                page(
                    "Access Expired",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Access Expired
                    </h1>

                    <p class="subtitle">
                        This access link has expired.
                    </p>
                    """,
                ),
            )

            return

        client_ip = (
            self.headers.get(
                "X-Real-IP"
            )
            or self.client_address[0]
        )

        client_ip = client_ip.strip()

        if not register_ip(
            row["id"],
            client_ip,
        ):

            self.send_html(
                400,
                page(
                    "Invalid Address",
                    """
                    <div class="icon">!</div>

                    <h1>
                        Invalid Client Address
                    </h1>

                    <p class="subtitle">
                        The client address could not be authorized.
                    </p>
                    """,
                ),
            )

            return

        username = html.escape(
            row["username"]
        )

        ip = html.escape(
            client_ip
        )

        remaining_days = max(
            0,
            int(
                (
                    expires
                    - now_utc()
                ).total_seconds()
                / 86400
            ),
        )

        expires_text = expires.strftime(
            "%Y-%m-%d"
        )

        body = f"""
        <div class="icon">
            ✓
        </div>

        <h1>
            DNS Access Activated
        </h1>

        <p class="subtitle">
            Your current public IP is now authorized.
        </p>

        <div class="status">
            <span class="dot"></span>
            DNS access is active
        </div>

        <div class="info">

            <div class="box">
                <span class="label">
                    User
                </span>

                <div class="value">
                    {username}
                </div>
            </div>

            <div class="box">
                <span class="label">
                    Current IP
                </span>

                <div class="value">
                    {ip}
                </div>
            </div>

            <div class="box">
                <span class="label">
                    Remaining
                </span>

                <div class="value">
                    {remaining_days} days
                </div>
            </div>

            <div class="box">
                <span class="label">
                    Expires
                </span>

                <div class="value">
                    {expires_text}
                </div>
            </div>

        </div>

        <div class="dns">

            <div class="label">
                DNS Configuration
            </div>

            <div class="dns-item">

                <span class="label">
                    DNS Server
                </span>

                <div class="dns-value">
                    {html.escape(SERVER_IP)}
                </div>

            </div>

            <div class="dns-item">

                <span class="label">
                    DNS over HTTPS
                </span>

                <div class="dns-value">
                    https://{html.escape(DOMAIN)}/dns-query
                </div>

            </div>

        </div>

        <p class="note">
            If your public IP changes,
            open this same link again
            to authorize the new IP address.
        </p>

        <div class="footer">
            Secure DNS Access
        </div>
        """

        self.send_html(
            200,
            page(
                "DNS Access Activated",
                body,
            ),
        )


def main():

    if not DOMAIN:
        raise RuntimeError(
            "DOMAIN is missing from configuration."
        )

    os.makedirs(
        os.path.dirname(
            NGINX_ALLOW_FILE
        ),
        exist_ok=True,
    )

    if not os.path.exists(
        NGINX_ALLOW_FILE
    ):

        with open(
            NGINX_ALLOW_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            f.write(
                "deny all;\n"
            )

    rebuild_nginx_allowlist()

    server = HTTPServer(
        (HOST, PORT),
        Handler,
    )

    print(
        "DNS access service listening "
        f"on {HOST}:{PORT}"
    )

    server.serve_forever()


if __name__ == "__main__":
    main()
