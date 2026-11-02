#!/usr/bin/env python3

import hashlib
import hmac
import secrets
import ipaddress
import logging
import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie, CookieError
from urllib.parse import parse_qs, unquote
from html import escape

DB_FILE = "/opt/dns-access/data/users.db"
HOST = os.getenv("DNS_ACCESS_HOST", "0.0.0.0")
PORT = int(os.getenv("DNS_ACCESS_PORT", "8787"))

logger = logging.getLogger(__name__)


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


def nft_run(args, log_failure=True):
    try:
        subprocess.run(
            ["/usr/sbin/nft", *args],
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


def nft_add_ip(ip, expires_at):
    if not valid_ip(ip):
        return False

    timeout = nft_timeout_seconds(expires_at)

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

    if nft_run(["replace", *element], log_failure=False):
        return True

    return nft_run(["add", *element])


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



def nft_expiry_for_ip(conn, ip, exclude_user_id=None, include_expiry=None):
    if not valid_ip(ip):
        return None

    now = now_utc()
    query = """
        SELECT id, expires_at
        FROM users
        WHERE disabled = 0
          AND (ip4 = ? OR ip6 = ?)
    """
    params = [ip, ip]

    if exclude_user_id is not None:
        query += " AND id != ?"
        params.append(exclude_user_id)

    rows = conn.execute(query, params).fetchall()
    expirations = []

    for row in rows:
        try:
            expiry = datetime.fromisoformat(row["expires_at"])
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry > now:
                expirations.append(expiry)
        except (TypeError, ValueError):
            logger.warning("Invalid expiration value found for an IP assignment")

    if include_expiry is not None:
        try:
            expiry = datetime.fromisoformat(include_expiry)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry > now:
                expirations.append(expiry)
        except (TypeError, ValueError):
            logger.warning("Invalid requested expiration value for an IP assignment")

    if not expirations:
        return None

    return max(expirations).isoformat()


def html_page(title, message, success=True, extra_html=""):
    status_class = "success" if success else "error"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{escape(title)}</title>
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
button {{
    padding: 12px 24px;
    border: 0;
    border-radius: 8px;
    background: #2563eb;
    color: white;
    font-size: 16px;
    cursor: pointer;
}}
</style>
</head>
<body>
<div class="card">
<h1 class="{status_class}">{escape(title)}</h1>
<p>{escape(message)}</p>
{extra_html}
</div>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format_string, *args):
        message = format_string % args

        if self.path.startswith("/join/"):
            message = message.replace(
                self.path,
                "/join/[redacted]",
            )

        print(message)

    def send_html(self, status, body, headers=None):
        encoded = body.encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
        )

        if headers:
            for name, value in headers:
                self.send_header(name, value)

        self.end_headers()
        self.wfile.write(encoded)

    def get_join_token(self):
        path = self.path.split("?", 1)[0]

        if not path.startswith("/join/"):
            return None

        return unquote(path[len("/join/"):]).strip()

    def find_active_user(self, conn, token):
        token_hash = hash_token(token)

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
            return None

        if user["disabled"]:
            self.send_html(
                403,
                html_page(
                    "Access Disabled",
                    "This access link has been disabled.",
                    False,
                ),
            )
            return None

        try:
            expires_at = datetime.fromisoformat(user["expires_at"])

            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

        except (ValueError, TypeError):
            self.send_html(
                500,
                html_page(
                    "Access Error",
                    "The access expiration date is invalid.",
                    False,
                ),
            )
            return None

        if expires_at <= now_utc():
            self.send_html(
                403,
                html_page(
                    "Access Expired",
                    "This access link has expired.",
                    False,
                ),
            )
            return None

        return user

    def do_GET(self):
        token = self.get_join_token()

        if token is None:
            self.send_html(
                404,
                html_page(
                    "Not Found",
                    "The requested page does not exist.",
                    False,
                ),
            )
            return

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

        conn = get_db()

        try:
            user = self.find_active_user(conn, token)

            if user is None:
                return

            csrf_token = secrets.token_urlsafe(32)
            action = escape(
                self.path.split("?", 1)[0],
                quote=True,
            )

            form_html = (
                f'<form method="post" action="{action}">'
                f'<input type="hidden" name="csrf_token" '
                f'value="{escape(csrf_token, quote=True)}">'
                '<button type="submit">Activate DNS Access</button>'
                '</form>'
            )

            cookie = (
                f"dns_access_csrf={csrf_token}; "
                "Path=/join/; HttpOnly; SameSite=Strict; Max-Age=600"
            )

            self.send_html(
                200,
                html_page(
                    "Confirm DNS Access",
                    "Press the button below to activate DNS access "
                    "for your current IP address.",
                    True,
                    form_html,
                ),
                [("Set-Cookie", cookie)],
            )

        finally:
            conn.close()

    def do_POST(self):
        token = self.get_join_token()

        if token is None or not token:
            self.send_html(
                404,
                html_page(
                    "Not Found",
                    "The requested page does not exist.",
                    False,
                ),
            )
            return

        content_type = self.headers.get(
            "Content-Type",
            "",
        ).split(";", 1)[0].strip().lower()

        if content_type != "application/x-www-form-urlencoded":
            self.send_html(
                415,
                html_page(
                    "Invalid Request",
                    "Unsupported request content type.",
                    False,
                ),
            )
            return

        content_length = self.headers.get("Content-Length", "")

        if not content_length.isdigit():
            self.send_html(
                411,
                html_page(
                    "Invalid Request",
                    "A valid request length is required.",
                    False,
                ),
            )
            return

        body_length = int(content_length)

        if body_length <= 0 or body_length > 4096:
            self.send_html(
                413,
                html_page(
                    "Invalid Request",
                    "The request body is invalid.",
                    False,
                ),
            )
            return

        try:
            body = self.rfile.read(body_length).decode("utf-8")
            form = parse_qs(
                body,
                strict_parsing=True,
                max_num_fields=10,
            )
        except (UnicodeDecodeError, ValueError):
            self.send_html(
                400,
                html_page(
                    "Invalid Request",
                    "The submitted form is invalid.",
                    False,
                ),
            )
            return

        submitted_tokens = form.get("csrf_token", [])

        if len(submitted_tokens) != 1:
            self.send_html(
                403,
                html_page(
                    "Request Rejected",
                    "The security token is missing or invalid.",
                    False,
                ),
            )
            return

        cookies = SimpleCookie()

        try:
            cookies.load(self.headers.get("Cookie", ""))
        except CookieError:
            cookies = SimpleCookie()

        csrf_cookie = cookies.get("dns_access_csrf")
        submitted_csrf = submitted_tokens[0]

        if (
            csrf_cookie is None
            or not submitted_csrf
            or not hmac.compare_digest(
                csrf_cookie.value,
                submitted_csrf,
            )
        ):
            self.send_html(
                403,
                html_page(
                    "Request Rejected",
                    "The security token is missing or invalid.",
                    False,
                ),
            )
            return

        conn = get_db()

        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError:
                logger.exception("Could not acquire database write transaction")
                self.send_html(
                    503,
                    html_page(
                        "Service Temporarily Unavailable",
                        "Please try again shortly.",
                        False,
                    ),
                )
                return

            user = self.find_active_user(conn, token)

            if user is None:
                return

            ip = client_ip(self)

            if not valid_ip(ip):
                self.send_html(
                    400,
                    html_page(
                        "Invalid Address",
                        "The client IP address is invalid.",
                        False,
                    ),
                )
                return

            old_ip4 = user["ip4"]
            old_ip6 = user["ip6"]

            if ":" in ip:
                current_ip = old_ip6
                ip4 = old_ip4
                ip6 = ip
            else:
                current_ip = old_ip4
                ip4 = ip
                ip6 = old_ip6

            shared_expiry = nft_expiry_for_ip(
                conn,
                ip,
                exclude_user_id=user["id"],
                include_expiry=user["expires_at"],
            )

            if shared_expiry is None:
                self.send_html(
                    400,
                    html_page(
                        "Expired Access",
                        "This access link has expired.",
                        False,
                    ),
                )
                return

            if not nft_add_ip(ip, shared_expiry):
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

            if current_ip and current_ip != ip:
                remaining_expiry = nft_expiry_for_ip(conn, current_ip)

                if remaining_expiry is None:
                    if not nft_delete_ip(current_ip):
                        logger.error(
                            "Could not remove obsolete IP address from nftables: %s",
                            current_ip,
                        )

            self.send_html(
                200,
                html_page(
                    "Access Activated",
                    f"DNS access has been activated for {ip}. "
                    f"Expiration: {user['expires_at']}",
                    True,
                ),
                [
                    (
                        "Set-Cookie",
                        "dns_access_csrf=; Path=/join/; "
                        "HttpOnly; SameSite=Strict; Max-Age=0",
                    )
                ],
            )

        finally:
            conn.close()

def main():
    conn = get_db()
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
