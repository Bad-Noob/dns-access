#!/usr/bin/env python3

import base64
import hashlib
import ipaddress
import os
import secrets
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from functools import wraps

from cryptography.fernet import Fernet
from flask import Flask, redirect, render_template_string, request, session, url_for


DB_FILE = "/opt/dns-access/data/users.db"
NGINX_ALLOW_FILE = "/etc/nginx/dns-allow.conf"

HOST = os.getenv("DNS_ADMIN_HOST", "127.0.0.1")
PORT = int(os.getenv("DNS_ADMIN_PORT", "8790"))

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
_password_b64 = os.getenv("ADMIN_PASSWORD_B64", "")
ADMIN_PASSWORD = (
    base64.b64decode(_password_b64, validate=True).decode("utf-8")
    if _password_b64
    else os.getenv("ADMIN_PASSWORD", "")
)

FLASK_SECRET = os.getenv("FLASK_SECRET", "")
LINK_ENCRYPTION_KEY = os.getenv("LINK_ENCRYPTION_KEY", "")

if not FLASK_SECRET:
    FLASK_SECRET = secrets.token_hex(32)

app = Flask(__name__)
app.secret_key = FLASK_SECRET

app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

fernet = Fernet(LINK_ENCRYPTION_KEY) if LINK_ENCRYPTION_KEY else None


def now_utc():
    return datetime.now(timezone.utc)


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_ip(ip):
    if not ip:
        return False

    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def nft_delete_ip(ip):
    if not valid_ip(ip):
        return False

    family = "dns6" if ":" in ip else "dns4"

    try:
        subprocess.run(
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
            ],
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

    lines = [f"allow {ip};" for ip in sorted(ips)]
    lines.append("deny all;")

    os.makedirs(os.path.dirname(NGINX_ALLOW_FILE), exist_ok=True)

    temp_file = NGINX_ALLOW_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")

    os.replace(temp_file, NGINX_ALLOW_FILE)

    if not os.path.exists("/etc/nginx/nginx.conf"):
        return

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


def remove_user_ips(row):
    for ip in (row["ip4"], row["ip6"]):
        nft_delete_ip(ip)


def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


BASE_STYLE = """
<style>
:root {
    color-scheme: dark;
    --bg: #0f172a;
    --card: #1e293b;
    --card2: #334155;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --danger: #f87171;
    --success: #4ade80;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: Arial, sans-serif;
}

.container {
    width: min(1180px, 94%);
    margin: 40px auto;
}

.card {
    background: var(--card);
    border-radius: 18px;
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 12px 35px rgba(0,0,0,.25);
}

h1, h2, h3 {
    margin-top: 0;
}

input, button {
    width: 100%;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid #475569;
    background: #0f172a;
    color: var(--text);
}

button {
    background: var(--accent);
    color: #082f49;
    font-weight: bold;
    cursor: pointer;
    border: 0;
}

button.danger {
    background: var(--danger);
    color: #450a0a;
}

button.success {
    background: var(--success);
    color: #052e16;
}

form {
    margin-bottom: 12px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    padding: 12px 8px;
    border-bottom: 1px solid #334155;
    text-align: left;
    vertical-align: top;
}

small {
    color: var(--muted);
}

a {
    color: var(--accent);
}

.badge {
    display: inline-block;
    padding: 5px 9px;
    border-radius: 999px;
    background: var(--card2);
}

.error {
    color: var(--danger);
}

.success-text {
    color: var(--success);
}
</style>
"""


LOGIN_HTML = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DNS Access Admin</title>
{BASE_STYLE}
</head>
<body>
<div class="container">
<div class="card" style="max-width:440px;margin:80px auto;">
<h1>DNS Access</h1>
<h2>Administrator Login</h2>
<form method="post">
<input name="username" placeholder="Username" required>
<br><br>
<input type="password" name="password" placeholder="Password" required>
<br><br>
<button type="submit">Sign in</button>
</form>
{{% if error %}}
<p class="error">{{{{ error }}}}</p>
{{% endif %}}
</div>
</div>
</body>
</html>
"""


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == ADMIN_USER and password == ADMIN_PASSWORD:
            session["authenticated"] = True
            return redirect(url_for("dashboard"))

        error = "Invalid username or password."

    return render_template_string(LOGIN_HTML, error=error)


@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/")
@login_required
def dashboard():
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM users
        ORDER BY id DESC
        """
    ).fetchall()

    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE disabled = 0
          AND expires_at > ?
        """,
        (now_utc().isoformat(),),
    ).fetchone()[0]

    disabled = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE disabled = 1
        """
    ).fetchone()[0]

    expired = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE expires_at <= ?
        """,
        (now_utc().isoformat(),),
    ).fetchone()[0]

    conn.close()

    return render_template_string(
        """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DNS Access Admin</title>
{{ style|safe }}
</head>
<body>
<div class="container">

<div class="card">
<h1>DNS Access Admin</h1>
<p>
<a href="{{ url_for('logout') }}">Logout</a>
</p>
</div>

<div class="grid">
<div class="card">
<small>Total</small>
<h2>{{ total }}</h2>
</div>

<div class="card">
<small>Active</small>
<h2>{{ active }}</h2>
</div>

<div class="card">
<small>Disabled</small>
<h2>{{ disabled }}</h2>
</div>

<div class="card">
<small>Expired</small>
<h2>{{ expired }}</h2>
</div>
</div>

<div class="card">
<h2>Create User</h2>

<form method="post" action="{{ url_for('create_user') }}">
<div class="grid">

<div>
<label>Username</label>
<input name="username" required>
</div>

<div>
<label>Days</label>
<input type="number" name="days" value="30" min="1" max="3650" required>
</div>

</div>

<br>

<button type="submit">Create User</button>
</form>
</div>

<div class="card">
<h2>Users</h2>

{% if rows %}
<table>
<thead>
<tr>
<th>User</th>
<th>Expires</th>
<th>IPv4</th>
<th>IPv6</th>
<th>Status</th>
<th>Actions</th>
</tr>
</thead>

<tbody>

{% for row in rows %}

<tr>
<td>
<strong>{{ row["username"] }}</strong>
<br>
<small>ID {{ row["id"] }}</small>
</td>

<td>
{{ row["expires_at"] }}
</td>

<td>
{{ row["ip4"] or "-" }}
</td>

<td>
{{ row["ip6"] or "-" }}
</td>

<td>
{% if row["disabled"] %}
<span class="badge">Disabled</span>
{% elif row["expires_at"] <= now %}
<span class="badge">Expired</span>
{% else %}
<span class="badge">Active</span>
{% endif %}
</td>

<td>

<form method="post" action="{{ url_for('renew_user', user_id=row['id']) }}">
<button class="success" type="submit">Renew 30d</button>
</form>

<form method="post" action="{{ url_for('toggle_user', user_id=row['id']) }}">
<button type="submit">
{% if row["disabled"] %}Enable{% else %}Disable{% endif %}
</button>
</form>

<form method="post" action="{{ url_for('delete_user', user_id=row['id']) }}">
<button class="danger" type="submit">Delete</button>
</form>

{% if row["link_enc"] %}
<form method="get" action="{{ url_for('show_link', user_id=row['id']) }}">
<button type="submit">Show Link</button>
</form>
{% endif %}

</td>
</tr>

{% endfor %}

</tbody>
</table>

{% else %}

<p>No users found.</p>

{% endif %}

</div>
</div>
</body>
</html>
        """,
        style=BASE_STYLE,
        rows=rows,
        total=total,
        active=active,
        disabled=disabled,
        expired=expired,
        now=now_utc().isoformat(),
    )


@app.route("/admin/create", methods=["POST"])
@login_required
def create_user():
    username = request.form.get("username", "").strip()
    days_raw = request.form.get("days", "30")

    if not username:
        return redirect(url_for("dashboard"))

    try:
        days = int(days_raw)
    except ValueError:
        days = 30

    days = max(1, min(days, 3650))

    token = secrets.token_urlsafe(32)
    token_hash = hash_token(token)

    created_at = now_utc()
    expires_at = created_at + timedelta(days=days)

    encrypted_link = None

    if fernet:
        link = f"/join/{token}"
        encrypted_link = fernet.encrypt(link.encode()).decode()

    conn = get_db()

    try:
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
            VALUES (?, ?, ?, NULL, NULL, 0, ?, ?, ?)
            """,
            (
                username,
                token_hash,
                expires_at.isoformat(),
                created_at.isoformat(),
                created_at.isoformat(),
                encrypted_link,
            ),
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()
        return redirect(url_for("dashboard"))

    conn.close()

    return redirect(url_for("show_new_link", token=token))


@app.route("/admin/new-link")
@login_required
def show_new_link():
    token = request.args.get("token", "").strip()

    if not token:
        return redirect(url_for("dashboard"))

    domain = request.host.split(":")[0]
    link = f"https://{domain}/join/{token}"

    return render_template_string(
        f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Access Link</title>
{BASE_STYLE}
</head>
<body>
<div class="container">
<div class="card">
<h1>Access Link Created</h1>
<p>Save this link and give it to the user.</p>
<input value="{link}" readonly>
<br><br>
<a href="/admin/">Back to dashboard</a>
</div>
</div>
</body>
</html>
        """
    )


@app.route("/admin/user/<int:user_id>/link")
@login_required
def show_link(user_id):
    conn = get_db()

    row = conn.execute(
        "SELECT link_enc FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    conn.close()

    if not row or not row["link_enc"] or not fernet:
        return redirect(url_for("dashboard"))

    try:
        link = fernet.decrypt(row["link_enc"].encode()).decode()
    except Exception:
        return redirect(url_for("dashboard"))

    domain = request.host.split(":")[0]
    full_link = f"https://{domain}{link}"

    return render_template_string(
        f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Access Link</title>
{BASE_STYLE}
</head>
<body>
<div class="container">
<div class="card">
<h1>Access Link</h1>
<input value="{full_link}" readonly>
<br><br>
<a href="/admin/">Back to dashboard</a>
</div>
</div>
</body>
</html>
        """
    )


@app.route("/admin/user/<int:user_id>/renew", methods=["POST"])
@login_required
def renew_user(user_id):
    conn = get_db()

    row = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if row:
        current_expiry = datetime.fromisoformat(row["expires_at"])

        if current_expiry.tzinfo is None:
            current_expiry = current_expiry.replace(tzinfo=timezone.utc)

        base = max(current_expiry, now_utc())
        new_expiry = base + timedelta(days=30)

        conn.execute(
            """
            UPDATE users
            SET expires_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_expiry.isoformat(),
                now_utc().isoformat(),
                user_id,
            ),
        )

        conn.commit()

    conn.close()

    return redirect(url_for("dashboard"))


@app.route("/admin/user/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_user(user_id):
    conn = get_db()

    row = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if row:
        new_disabled = 0 if row["disabled"] else 1

        conn.execute(
            """
            UPDATE users
            SET disabled = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_disabled,
                now_utc().isoformat(),
                user_id,
            ),
        )

        conn.commit()

        if new_disabled:
            remove_user_ips(row)

        rebuild_nginx_allowlist(conn)

    conn.close()

    return redirect(url_for("dashboard"))


@app.route("/admin/user/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    conn = get_db()

    row = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

    if row:
        remove_user_ips(row)

        conn.execute(
            "DELETE FROM users WHERE id = ?",
            (user_id,),
        )

        conn.commit()

        rebuild_nginx_allowlist(conn)

    conn.close()

    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    app.run(
        host=HOST,
        port=PORT,
        debug=False,
    )
