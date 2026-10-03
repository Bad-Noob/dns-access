#!/usr/bin/env python3

import base64
import hashlib
import html
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

from cryptography.fernet import Fernet
from flask import (
    Flask,
    redirect,
    render_template_string,
    request,
    session,
)


CONFIG_FILE = "/etc/dns-access.conf"
ENV_FILE = "/etc/dns-admin.env"
DB_FILE = "/opt/dns-access/data/users.db"


def load_config():
    config = {}

    if not os.path.exists(CONFIG_FILE):
        return config

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            config[key.strip()] = value.strip().strip('"').strip("'")

    return config


def load_env():
    values = {}

    if not os.path.exists(ENV_FILE):
        return values

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")

    return values


CONFIG = load_config()
ENV = load_env()

DOMAIN = CONFIG.get("DOMAIN", "")
ADMIN_USER = ENV.get("ADMIN_USER", "")
ADMIN_PASSWORD = ENV.get("ADMIN_PASSWORD", "")
LINK_KEY = ENV.get("LINK_ENCRYPTION_KEY", "")

BASE_URL = f"https://{DOMAIN}"


if LINK_KEY:
    FERNET = Fernet(LINK_KEY.encode())
else:
    FERNET = None


app = Flask(__name__)

app.secret_key = ENV.get(
    "FLASK_SECRET",
    secrets.token_hex(32),
)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


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
            updated_at TEXT
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
            "ALTER TABLE users ADD COLUMN link_enc TEXT"
        )

    conn.commit()

    return conn


def encrypt_link(link):
    if not FERNET:
        return ""

    return FERNET.encrypt(
        link.encode()
    ).decode()


def decrypt_link(value):
    if not value or not FERNET:
        return ""

    try:
        return FERNET.decrypt(
            value.encode()
        ).decode()
    except Exception:
        return ""


def login_required():
    if not session.get("authenticated"):
        return redirect("/admin/login")

    return None


def prepare_users(rows):
    result = []

    for row in rows:
        item = dict(row)

        item["link"] = decrypt_link(
            item.get("link_enc", "")
        )

        try:
            expires = datetime.fromisoformat(
                item["expires_at"].replace("Z", "+00:00")
            )

            if expires.tzinfo is None:
                expires = expires.replace(
                    tzinfo=timezone.utc
                )

            days_left = max(
                0,
                int(
                    (
                        expires - now_utc()
                    ).total_seconds() / 86400
                ),
            )

        except Exception:
            days_left = 0

        item["days_left"] = days_left
        item["days_percent"] = min(
            100,
            int((days_left / 30) * 100),
        )

        result.append(item)

    return result


HTML = """
<!doctype html>
<html lang="en">
<head>

<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>DNS Access Admin</title>

<style>

:root {
    --bg:#f1f5f9;
    --card:#ffffff;
    --text:#0f172a;
    --muted:#64748b;
    --border:#e2e8f0;
    --input:#ffffff;
    --primary:#6366f1;
    --primary2:#4f46e5;
    --green:#16a34a;
    --red:#dc2626;
    --orange:#d97706;
    --shadow:0 10px 30px rgba(15,23,42,.08);
}

[data-theme="dark"] {
    --bg:#0b1120;
    --card:#111827;
    --text:#f8fafc;
    --muted:#94a3b8;
    --border:#263244;
    --input:#0f172a;
    --primary:#818cf8;
    --primary2:#6366f1;
    --green:#4ade80;
    --red:#f87171;
    --orange:#fbbf24;
    --shadow:0 15px 40px rgba(0,0,0,.35);
}

* {
    box-sizing:border-box;
}

body {
    margin:0;
    background:var(--bg);
    color:var(--text);
    font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.container {
    width:min(1450px, calc(100% - 32px));
    margin:30px auto;
}

.topbar {
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:15px;
    margin-bottom:24px;
}

.brand h1 {
    margin:0;
    font-size:27px;
}

.brand p {
    margin:5px 0 0;
    color:var(--muted);
    font-size:13px;
}

.top-actions {
    display:flex;
    gap:8px;
}

button,
input {
    font:inherit;
}

.btn {
    border:1px solid var(--border);
    background:var(--card);
    color:var(--text);
    border-radius:10px;
    padding:9px 13px;
    cursor:pointer;
}

.btn.primary {
    background:var(--primary);
    border-color:var(--primary);
    color:white;
}

.btn.danger {
    color:var(--red);
}

.stats {
    display:grid;
    grid-template-columns:
        repeat(3, minmax(0,1fr));
    gap:14px;
    margin-bottom:18px;
}

.stat {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:18px;
    padding:18px;
    box-shadow:var(--shadow);
}

.stat-label {
    color:var(--muted);
    font-size:12px;
    font-weight:700;
}

.stat-value {
    margin-top:7px;
    font-size:28px;
    font-weight:800;
}

.card {
    background:var(--card);
    border:1px solid var(--border);
    border-radius:20px;
    box-shadow:var(--shadow);
    padding:20px;
    margin-bottom:18px;
}

.card h2 {
    margin:0 0 15px;
    font-size:18px;
}

.add-form {
    display:grid;
    grid-template-columns:
        1fr 180px auto;
    gap:10px;
}

.input {
    width:100%;
    border:1px solid var(--border);
    background:var(--input);
    color:var(--text);
    border-radius:10px;
    padding:11px 12px;
    outline:none;
}

.input:focus {
    border-color:var(--primary);
}

.search {
    margin-bottom:14px;
}

.table-wrap {
    overflow:auto;
}

table {
    width:100%;
    border-collapse:collapse;
    min-width:1050px;
}

th,
td {
    padding:13px 10px;
    border-bottom:1px solid var(--border);
    text-align:left;
    vertical-align:middle;
}

th {
    color:var(--muted);
    font-size:11px;
    text-transform:uppercase;
    letter-spacing:.04em;
}

.user {
    font-weight:700;
}

.ip {
    font-family:
        ui-monospace,
        SFMono-Regular,
        Menlo,
        monospace;
    font-size:12px;
}

.modern-link {
    display:flex;
    align-items:center;
    gap:8px;
    min-width:260px;
    max-width:360px;
    padding:8px 10px;
    border:1px solid var(--border);
    border-radius:12px;
    background:var(--card);
}

.link-text {
    flex:1;
    min-width:0;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    font-family:
        ui-monospace,
        SFMono-Regular,
        Menlo,
        monospace;
    font-size:12px;
}

.link-copy {
    flex:none;
    padding:7px 11px;
    border:0;
    border-radius:9px;
    background:var(--primary);
    color:white;
    font-size:12px;
    font-weight:700;
    cursor:pointer;
}

.days-wrap {
    display:flex;
    align-items:center;
    gap:8px;
}

.days-ring {
    --size:48px;
    width:var(--size);
    height:var(--size);
    border-radius:50%;
    display:grid;
    place-items:center;
    position:relative;
    background:
        conic-gradient(
            var(--primary)
            var(--progress),
            var(--border) 0
        );
}

.days-ring::before {
    content:"";
    position:absolute;
    inset:5px;
    border-radius:50%;
    background:var(--card);
}

.days-ring span {
    position:relative;
    z-index:1;
    font-size:13px;
    font-weight:800;
}

.days-label {
    font-size:11px;
    color:var(--muted);
    font-weight:600;
}

.badge {
    display:inline-block;
    padding:5px 9px;
    border-radius:999px;
    font-size:11px;
    font-weight:700;
}

.badge.active {
    color:var(--green);
    background:rgba(22,163,74,.10);
}

.badge.disabled {
    color:var(--red);
    background:rgba(220,38,38,.10);
}

.badge.expired {
    color:var(--orange);
    background:rgba(217,119,6,.10);
}

.actions {
    display:flex;
    flex-wrap:wrap;
    gap:6px;
}

.action {
    border:1px solid var(--border);
    background:var(--card);
    color:var(--text);
    border-radius:8px;
    padding:7px 9px;
    cursor:pointer;
    font-size:11px;
}

.action.danger {
    color:var(--red);
}

.notice {
    padding:12px 14px;
    border-radius:12px;
    margin-bottom:18px;
    background:rgba(99,102,241,.10);
    color:var(--text);
    font-size:13px;
}

@media(max-width:800px) {
    .stats {
        grid-template-columns:1fr;
    }

    .add-form {
        grid-template-columns:1fr;
    }

    .topbar {
        align-items:flex-start;
        flex-direction:column;
    }
}

</style>

</head>

<body>

<div class="container">

<div class="topbar">

<div class="brand">
    <h1>DNS Access Admin</h1>
    <p>User and access management</p>
</div>

<div class="top-actions">

<button
    class="btn"
    id="themeBtn"
    onclick="toggleTheme()">
    🌙 Dark
</button>

<a
    class="btn"
    href="/admin/logout">
    Logout
</a>

</div>

</div>

{% if message %}
<div class="notice">
    {{ message }}
</div>
{% endif %}

<div class="stats">

<div class="stat">
    <div class="stat-label">TOTAL USERS</div>
    <div class="stat-value">{{ total }}</div>
</div>

<div class="stat">
    <div class="stat-label">ACTIVE</div>
    <div class="stat-value">{{ active }}</div>
</div>

<div class="stat">
    <div class="stat-label">DISABLED</div>
    <div class="stat-value">{{ disabled }}</div>
</div>

</div>

<div class="card">

<h2>Add User</h2>

<form
    class="add-form"
    method="post"
    action="/admin/add">

<input
    class="input"
    type="text"
    name="username"
    placeholder="Username"
    required>

<input
    class="input"
    type="number"
    name="days"
    min="1"
    value="30"
    placeholder="Days"
    required>

<button
    class="btn primary"
    type="submit">
    Create User
</button>

</form>

</div>

<div class="card">

<h2>Users</h2>

<form method="get" class="search">
<input
    class="input"
    name="q"
    value="{{ q }}"
    placeholder="Search users...">
</form>

<div class="table-wrap">

<table>

<tr>
<th>ID</th>
<th>User</th>
<th>Access Link</th>
<th>Remaining</th>
<th>IPv4</th>
<th>Status</th>
<th>Actions</th>
</tr>

{% for u in users %}

<tr>

<td>{{ u.id }}</td>

<td class="user">
    {{ u.username }}
</td>

<td>

<div class="modern-link">

<div
    class="link-text"
    title="{{ u.link }}">
    {{ u.link[:38] }}
    {% if u.link|length > 38 %}...{% endif %}
</div>

<button
    class="link-copy"
    onclick="copyLink('{{ u.link|e }}', this)"
    type="button">
    Copy
</button>

</div>

</td>

<td>

<div class="days-wrap">

<div
    class="days-ring"
    style="--progress: {{ u.days_percent }}%;">
    <span>{{ u.days_left }}</span>
</div>

<div class="days-label">
    days
</div>

</div>

</td>

<td class="ip">
    {{ u.ip4 or "-" }}
</td>

<td>

{% if u.disabled %}

<span class="badge disabled">
    Disabled
</span>

{% elif u.expires_at <= now %}

<span class="badge expired">
    Expired
</span>

{% else %}

<span class="badge active">
    Active
</span>

{% endif %}

</td>

<td>

<div class="actions">

<form
    method="post"
    action="/admin/renew/{{ u.id }}"
    onsubmit="return confirm('Renew {{ u.username }} for 30 days?')">

<button
    class="action"
    type="submit">
    ↻ Renew
</button>

</form>

{% if u.disabled %}

<form
    method="post"
    action="/admin/enable/{{ u.id }}"
    onsubmit="return confirm('Enable {{ u.username }}?')">

<button
    class="action"
    type="submit">
    ▶ Enable
</button>

</form>

{% else %}

<form
    method="post"
    action="/admin/disable/{{ u.id }}"
    onsubmit="return confirm('Disable {{ u.username }}?')">

<button
    class="action"
    type="submit">
    ⏸ Disable
</button>

</form>

{% endif %}

<form
    method="post"
    action="/admin/delete/{{ u.id }}"
    onsubmit="return confirm('DELETE {{ u.username }} permanently?')">

<button
    class="action danger"
    type="submit">
    ✕ Delete
</button>

</form>

</div>

</td>

</tr>

{% endfor %}

{% if not users %}

<tr>

<td
    colspan="7"
    style="text-align:center;color:var(--muted);padding:35px">

No users found.

</td>

</tr>

{% endif %}

</table>

</div>

</div>

</div>

<script>

function toggleTheme() {

    const html =
        document.documentElement;

    const dark =
        html.getAttribute("data-theme")
        === "dark";

    if (dark) {

        html.removeAttribute("data-theme");

        localStorage.setItem(
            "dns-theme",
            "light"
        );

    } else {

        html.setAttribute(
            "data-theme",
            "dark"
        );

        localStorage.setItem(
            "dns-theme",
            "dark"
        );
    }

    updateThemeButton();
}


function updateThemeButton() {

    const dark =
        document.documentElement
        .getAttribute("data-theme")
        === "dark";

    document.getElementById(
        "themeBtn"
    ).textContent =
        dark ? "☀️ Light" : "🌙 Dark";
}


if (
    localStorage.getItem("dns-theme")
    === "dark"
) {
    document.documentElement
        .setAttribute(
            "data-theme",
            "dark"
        );
}


updateThemeButton();


async function copyLink(link, button) {

    try {

        await navigator.clipboard
            .writeText(link);

        const old =
            button.textContent;

        button.textContent =
            "✓ Copied";

        setTimeout(
            () => button.textContent = old,
            1500
        );

    } catch {

        prompt(
            "Copy this link:",
            link
        );
    }
}

</script>

</body>
</html>
"""


LOGIN_HTML = """
<!doctype html>
<html lang="en">

<head>

<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Admin Login</title>

<style>

:root {
    --bg:#f1f5f9;
    --card:#ffffff;
    --text:#0f172a;
    --muted:#64748b;
    --border:#e2e8f0;
    --primary:#6366f1;
}

[data-theme="dark"] {
    --bg:#0b1120;
    --card:#111827;
    --text:#f8fafc;
    --muted:#94a3b8;
    --border:#263244;
    --primary:#818cf8;
}

* {
    box-sizing:border-box;
}

body {
    margin:0;
    min-height:100vh;
    display:flex;
    align-items:center;
    justify-content:center;
    padding:20px;
    background:var(--bg);
    color:var(--text);
    font-family:
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.card {
    width:100%;
    max-width:400px;
    padding:28px;
    background:var(--card);
    border:1px solid var(--border);
    border-radius:22px;
}

h1 {
    margin:0 0 8px;
    text-align:center;
}

p {
    margin:0 0 22px;
    color:var(--muted);
    text-align:center;
    font-size:13px;
}

.input {
    width:100%;
    margin-bottom:10px;
    padding:12px;
    border:1px solid var(--border);
    border-radius:10px;
    background:var(--card);
    color:var(--text);
}

button {
    width:100%;
    padding:12px;
    border:0;
    border-radius:10px;
    background:var(--primary);
    color:white;
    font-weight:700;
    cursor:pointer;
}

.error {
    margin-bottom:12px;
    padding:10px;
    border-radius:9px;
    background:rgba(220,38,38,.10);
    color:#dc2626;
    font-size:12px;
    text-align:center;
}

</style>

</head>

<body>

<div class="card">

<h1>DNS Access Admin</h1>

<p>
    Sign in to continue
</p>

{% if error %}
<div class="error">
    {{ error }}
</div>
{% endif %}

<form method="post">

<input
    class="input"
    type="text"
    name="username"
    placeholder="Username"
    autocomplete="username"
    required>

<input
    class="input"
    type="password"
    name="password"
    placeholder="Password"
    autocomplete="current-password"
    required>

<button type="submit">
    Sign in
</button>

</form>

</div>

<script>

if (
    localStorage.getItem("dns-theme")
    === "dark"
) {
    document.documentElement
        .setAttribute(
            "data-theme",
            "dark"
        );
}

</script>

</body>
</html>
"""


@app.route("/admin/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get(
            "username",
            "",
        ).strip()

        password = request.form.get(
            "password",
            "",
        )

        if (
            secrets.compare_digest(
                username,
                ADMIN_USER,
            )
            and secrets.compare_digest(
                password,
                ADMIN_PASSWORD,
            )
        ):

            session.clear()
            session["authenticated"] = True

            return redirect("/admin/")

        return render_template_string(
            LOGIN_HTML,
            error="Invalid username or password.",
        )

    return render_template_string(
        LOGIN_HTML,
        error=None,
    )


@app.route("/admin/logout")
def logout():

    session.clear()

    return redirect("/admin/login")


@app.route("/admin/")
def index():

    denied = login_required()

    if denied:
        return denied

    q = request.args.get(
        "q",
        "",
    ).strip()

    conn = get_db()

    if q:

        rows = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username LIKE ?
            ORDER BY id DESC
            """,
            (f"%{q}%",),
        ).fetchall()

    else:

        rows = conn.execute(
            """
            SELECT *
            FROM users
            ORDER BY id DESC
            """
        ).fetchall()

    stats = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(
                CASE
                    WHEN disabled = 0
                     AND expires_at > ?
                    THEN 1 ELSE 0
                END
            ) AS active,
            SUM(
                CASE
                    WHEN disabled = 1
                    THEN 1 ELSE 0
                END
            ) AS disabled
        FROM users
        """,
        (now_utc().isoformat(),),
    ).fetchone()

    conn.close()

    users = prepare_users(rows)

    return render_template_string(
        HTML,
        users=users,
        q=q,
        now=now_utc().isoformat(),
        total=stats["total"] or 0,
        active=stats["active"] or 0,
        disabled=stats["disabled"] or 0,
        message=request.args.get("message", ""),
    )


@app.route(
    "/admin/add",
    methods=["POST"],
)
def add_user():

    denied = login_required()

    if denied:
        return denied

    username = request.form.get(
        "username",
        "",
    ).strip()

    days = request.form.get(
        "days",
        "",
    ).strip()

    if not username:
        return "Invalid username", 400

    if not days.isdigit():
        return "Invalid days", 400

    days = int(days)

    if days < 1 or days > 3650:
        return "Invalid days", 400

    token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        token.encode()
    ).hexdigest()

    expires = (
        now_utc()
        + timedelta(days=days)
    ).isoformat()

    link = (
        BASE_URL
        + "/join/"
        + token
    )

    link_enc = encrypt_link(link)

    conn = get_db()

    try:

        conn.execute(
            """
            INSERT INTO users
            (
                username,
                token_hash,
                expires_at,
                disabled,
                created_at,
                updated_at,
                link_enc
            )
            VALUES (?, ?, ?, 0, ?, ?, ?)
            """,
            (
                username,
                token_hash,
                expires,
                now_utc().isoformat(),
                now_utc().isoformat(),
                link_enc,
            ),
        )

        conn.commit()

    except sqlite3.IntegrityError:

        conn.close()

        return "Username already exists", 409

    finally:

        conn.close()

    return render_template_string(
        """
        <!doctype html>
        <html>
        <head>
        <meta charset="utf-8">
        <meta name="viewport"
              content="width=device-width,initial-scale=1">
        <title>User Created</title>

        <style>

        :root {
            --bg:#f1f5f9;
            --card:#ffffff;
            --text:#0f172a;
            --muted:#64748b;
            --border:#e2e8f0;
            --primary:#6366f1;
            --green:#16a34a;
        }

        [data-theme="dark"] {
            --bg:#0b1120;
            --card:#111827;
            --text:#f8fafc;
            --muted:#94a3b8;
            --border:#263244;
            --primary:#818cf8;
            --green:#4ade80;
        }

        * {
            box-sizing:border-box;
        }

        body {
            margin:0;
            min-height:100vh;
            display:flex;
            align-items:center;
            justify-content:center;
            padding:20px;
            background:var(--bg);
            color:var(--text);
            font-family:system-ui,sans-serif;
        }

        .card {
            width:100%;
            max-width:600px;
            padding:28px;
            background:var(--card);
            border:1px solid var(--border);
            border-radius:22px;
        }

        .icon {
            width:58px;
            height:58px;
            margin:0 auto 15px;
            display:grid;
            place-items:center;
            border-radius:50%;
            background:rgba(22,163,74,.10);
            color:var(--green);
            font-size:27px;
            font-weight:800;
        }

        h1 {
            margin:0;
            text-align:center;
        }

        .subtitle {
            margin:8px 0 22px;
            text-align:center;
            color:var(--muted);
        }

        .box {
            padding:15px;
            border:1px solid var(--border);
            border-radius:13px;
            margin-bottom:10px;
        }

        .label {
            display:block;
            margin-bottom:7px;
            color:var(--muted);
            font-size:11px;
            font-weight:700;
            text-transform:uppercase;
        }

        .link {
            word-break:break-all;
            font-family:monospace;
            font-size:13px;
        }

        .copy {
            width:100%;
            margin-top:10px;
            padding:11px;
            border:0;
            border-radius:10px;
            background:var(--primary);
            color:white;
            font-weight:700;
            cursor:pointer;
        }

        .back {
            display:block;
            margin-top:15px;
            text-align:center;
            color:var(--primary);
            text-decoration:none;
        }

        </style>
        </head>

        <body>

        <div class="card">

        <div class="icon">✓</div>

        <h1>User Created</h1>

        <p class="subtitle">
            The access link has been generated successfully.
        </p>

        <div class="box">
            <span class="label">Username</span>
            {{ username }}
        </div>

        <div class="box">
            <span class="label">Expires</span>
            {{ expires }}
        </div>

        <div class="box">

            <span class="label">
                Access Link
            </span>

            <div
                class="link"
                id="link">
                {{ link }}
            </div>

            <button
                class="copy"
                onclick="copyLink()">
                Copy Access Link
            </button>

        </div>

        <a
            class="back"
            href="/admin/">
            ← Back to Admin
        </a>

        </div>

        <script>

        if (
            localStorage.getItem("dns-theme")
            === "dark"
        ) {
            document.documentElement
                .setAttribute(
                    "data-theme",
                    "dark"
                );
        }

        async function copyLink() {

            const link =
                document.getElementById(
                    "link"
                ).textContent.trim();

            await navigator.clipboard
                .writeText(link);

            alert("Link copied.");

        }

        </script>

        </body>
        </html>
        """,
        username=html.escape(username),
        expires=html.escape(expires),
        link=html.escape(link),
    )


@app.route(
    "/admin/renew/<int:user_id>",
    methods=["POST"],
)
def renew(user_id):

    denied = login_required()

    if denied:
        return denied

    conn = get_db()

    row = conn.execute(
        """
        SELECT expires_at
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()

    if row:

        try:
            expires = datetime.fromisoformat(
                row["expires_at"].replace(
                    "Z",
                    "+00:00",
                )
            )

            if expires.tzinfo is None:
                expires = expires.replace(
                    tzinfo=timezone.utc
                )

        except ValueError:
            expires = now_utc()

        if expires < now_utc():
            expires = now_utc()

        expires += timedelta(days=30)

        conn.execute(
            """
            UPDATE users
            SET expires_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                expires.isoformat(),
                now_utc().isoformat(),
                user_id,
            ),
        )

        conn.commit()

    conn.close()

    return redirect(
        "/admin/?message=User renewed"
    )


@app.route(
    "/admin/disable/<int:user_id>",
    methods=["POST"],
)
def disable(user_id):

    denied = login_required()

    if denied:
        return denied

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET disabled = 1,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now_utc().isoformat(),
            user_id,
        ),
    )

    conn.commit()
    conn.close()

    return redirect(
        "/admin/?message=User disabled"
    )


@app.route(
    "/admin/enable/<int:user_id>",
    methods=["POST"],
)
def enable(user_id):

    denied = login_required()

    if denied:
        return denied

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET disabled = 0,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now_utc().isoformat(),
            user_id,
        ),
    )

    conn.commit()
    conn.close()

    return redirect(
        "/admin/?message=User enabled"
    )


@app.route(
    "/admin/delete/<int:user_id>",
    methods=["POST"],
)
def delete_user(user_id):

    denied = login_required()

    if denied:
        return denied

    conn = get_db()

    conn.execute(
        """
        DELETE FROM users
        WHERE id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()

    return redirect(
        "/admin/?message=User deleted"
    )


if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=8790,
        debug=False,
    )
