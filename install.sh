#!/usr/bin/env bash

set -euo pipefail

REPO_URL="https://github.com/Bad-Noob/dns-access.git"
ADGUARD_VERSION="v0.107.79"
RAW_BASE_URL="https://raw.githubusercontent.com/Bad-Noob/dns-access/main"

INSTALL_DIR="/opt/dns-access"
ADMIN_DIR="/opt/dns-admin"
CONFIG_DIR="/etc/dns-access"
TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "$TMP_DIR"
}

trap cleanup EXIT

log() {
    printf '\n[%s] %s\n' "INFO" "$1"
}

ok() {
    printf '[OK] %s\n' "$1"
}

error() {
    printf '[ERROR] %s\n' "$1" >&2
}

die() {
    error "$1"
    exit 1
}

require_root() {
    [[ "${EUID}" -eq 0 ]] || die "Run this installer as root."
}

require_tty() {
    [[ -r /dev/tty && -w /dev/tty ]] || die "Interactive terminal required. Run this installer from an interactive shell."
}

check_os() {
    [[ -f /etc/os-release ]] || die "Cannot detect operating system."

    source /etc/os-release

    [[ "${ID:-}" == "ubuntu" ]] || die "Ubuntu is required."

    ok "Ubuntu detected: ${PRETTY_NAME}"
}

install_packages() {
    log "Installing required packages..."

    export DEBIAN_FRONTEND=noninteractive

    apt-get update

    apt-get install -y \
        ca-certificates \
        curl \
        wget \
        git \
        gnupg \
        unzip \
        tar \
        openssl \
        apache2-utils \
        python3 \
        python3-venv \
        python3-pip \
        nftables \
        unbound \
        unbound-anchor \
        dnsutils \
        sqlite3 \
        jq \
        iproute2 \
        logrotate

    ok "Required packages installed."
}

ask_value() {
    local prompt="$1"
    local default_value="${2:-}"
    local value

    if [[ -n "$default_value" ]]; then
        read -r -p "$prompt [$default_value]: " value </dev/tty
        value="${value:-$default_value}"
    else
        read -r -p "$prompt: " value </dev/tty
    fi

    printf '%s' "$value"
}

ask_password() {
    local prompt="$1"
    local password
    local confirm

    while true; do
        read -r -s -p "$prompt: " password </dev/tty
        printf '\n' >&2

        read -r -s -p "Confirm password: " confirm </dev/tty
        printf '\n' >&2

        if [[ "$password" != "$confirm" ]]; then
            echo "Passwords do not match." >&2
            continue
        fi

        if [[ "${#password}" -lt 12 ]]; then
            echo "Password must contain at least 12 characters." >&2
            continue
        fi

        printf '%s' "$password"
        return
    done
}
validate_ipv4() {
    local ip="$1"

    python3 - "$ip" <<'PY'
import ipaddress
import sys

try:
    ip = ipaddress.ip_address(sys.argv[1])
    raise SystemExit(0 if ip.version == 4 else 1)
except ValueError:
    raise SystemExit(1)
PY
}

validate_ipv6() {
    local ip="$1"

    python3 - "$ip" <<'PY'
import ipaddress
import sys

try:
    ip = ipaddress.ip_address(sys.argv[1])
    raise SystemExit(0 if ip.version == 6 else 1)
except ValueError:
    raise SystemExit(1)
PY
}



ask_configuration() {
    echo
    echo "========================================"
    echo " DNS Access Installation"
    echo "========================================"
    echo

    SERVER_IP="$(ask_value "Public IPv4 address")"

    while ! validate_ipv4 "$SERVER_IP"; do
        echo "Invalid IPv4 address."
        SERVER_IP="$(ask_value "Public IPv4 address")"
    done

    ADMIN_USER="$(ask_value "Administrator username" "admin")"

    while [[ ! "$ADMIN_USER" =~ ^[a-zA-Z0-9._-]{3,32}$ ]]; do
        echo "Invalid administrator username."
        ADMIN_USER="$(ask_value "Administrator username" "admin")"
    done

    ADMIN_PASSWORD="$(ask_password "Administrator password")"

    ADGUARD_USER="$(ask_value "AdGuard username" "adguard")"

    while [[ ! "$ADGUARD_USER" =~ ^[a-zA-Z0-9._-]{3,32}$ ]]; do
        echo "Invalid AdGuard username."
        ADGUARD_USER="$(ask_value "AdGuard username" "adguard")"
    done

    while true; do
        ADGUARD_PASSWORD="$(ask_password "AdGuard password")"
        ADGUARD_PASSWORD_BYTES="$(printf '%s' "$ADGUARD_PASSWORD" | wc -c)"

        if (( ADGUARD_PASSWORD_BYTES <= 72 )); then
            break
        fi

        echo "AdGuard password must not exceed 72 bytes."
    done

    echo
    echo "IPv4 DNS support:"
    echo "1) Enabled"
    echo "2) Disabled"

    read -r -p "Choose [1]: " IPV4_CHOICE </dev/tty
    IPV4_CHOICE="${IPV4_CHOICE:-1}"

    case "$IPV4_CHOICE" in
        1)
            IPV4_ENABLED="true"
            ;;
        2)
            IPV4_ENABLED="false"
            ;;
        *)
            die "Invalid IPv4 option."
            ;;
    esac

    echo
    echo "IPv6 DNS support:"
    echo "1) Enabled"
    echo "2) Disabled"

    read -r -p "Choose [2]: " IPV6_CHOICE </dev/tty
    IPV6_CHOICE="${IPV6_CHOICE:-2}"

    case "$IPV6_CHOICE" in
        1)
            IPV6_ENABLED="true"
            ;;
        2)
            IPV6_ENABLED="false"
            ;;
        *)
            die "Invalid IPv6 option."
            ;;
    esac

    if [[ "$IPV6_ENABLED" == "true" ]]; then
        SERVER_IPV6="$(ask_value "Public IPv6 address")"

        while ! validate_ipv6 "$SERVER_IPV6"; do
            echo "Invalid IPv6 address."
            SERVER_IPV6="$(ask_value "Public IPv6 address")"
        done
    else
        SERVER_IPV6=""
    fi

    DNS_UPSTREAM_MODE="recursive"
    DNS_UPSTREAM_1=""
    DNS_UPSTREAM_2=""

    echo
    echo "========================================"
    echo " Configuration Summary"
    echo "========================================"
    echo
    echo "Public IPv4 : $SERVER_IP"
    echo "Public IPv6 : ${SERVER_IPV6:-disabled}"
    echo "Admin user  : $ADMIN_USER"
    echo "IPv4 DNS    : $IPV4_ENABLED"
    echo "IPv6 DNS    : $IPV6_ENABLED"
    echo

    read -r -p "Continue installation? [y/N]: " CONFIRM </dev/tty

    [[ "$CONFIRM" =~ ^[Yy]$ ]] || die "Installation cancelled."
}

prepare_directories() {
    log "Preparing directories..."

    mkdir -p \
        "$INSTALL_DIR/app" \
        "$INSTALL_DIR/data" \
        "$ADMIN_DIR/app" \
        /var/log/dns-access \
        /var/log/dns-admin \
        "$CONFIG_DIR"

    chmod 700 "$INSTALL_DIR"
    chmod 700 "$INSTALL_DIR/data"
    chmod 700 "$ADMIN_DIR"
    chmod 700 "$CONFIG_DIR"

    chmod 750 /var/log/dns-access
    chmod 750 /var/log/dns-admin

    ok "Directories prepared."
}

download_project() {
    log "Preparing project files..."

    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

    if [[ -d "$SCRIPT_DIR/dns-access" && -d "$SCRIPT_DIR/dns-admin" && -d "$SCRIPT_DIR/config" ]]; then
        mkdir -p "$TMP_DIR/repository"
        cp -a "$SCRIPT_DIR/." "$TMP_DIR/repository/"
        rm -rf "$TMP_DIR/repository/.git"
        log "Using local project files."
    else
        git clone --depth 1 "$REPO_URL" "$TMP_DIR/repository"
    fi

    [[ -d "$TMP_DIR/repository/dns-access" ]] || die "Project download is incomplete."
    [[ -d "$TMP_DIR/repository/dns-admin" ]] || die "Project download is incomplete."
    [[ -d "$TMP_DIR/repository/config" ]] || die "Project configuration is missing."

    ok "Project downloaded."
}

install_project_files() {
    log "Installing project files..."

    cp "$TMP_DIR/repository/dns-access/app.py" \
        "$INSTALL_DIR/app/app.py"

    cp "$TMP_DIR/repository/dns-access/maintenance.py" \
        "$INSTALL_DIR/app/maintenance.py"

    cp "$TMP_DIR/repository/dns-access/healthcheck.sh" \
        "$INSTALL_DIR/healthcheck.sh"

    cp "$TMP_DIR/repository/dns-admin/app.py" \
        "$ADMIN_DIR/app/app.py"

    chmod 750 "$INSTALL_DIR/healthcheck.sh"

    cp "$TMP_DIR/repository/config/nftables.conf" \
        "$CONFIG_DIR/nftables.conf"

    cp "$TMP_DIR/repository/config/dns-access.service" \
        /etc/systemd/system/dns-access.service

    cp "$TMP_DIR/repository/config/dns-admin.service" \
        /etc/systemd/system/dns-admin.service

    cp "$TMP_DIR/repository/config/unbound.service" \
        /etc/systemd/system/unbound.service

    cp "$TMP_DIR/repository/config/dns-maintenance.service" \
        /etc/systemd/system/dns-maintenance.service

    cp "$TMP_DIR/repository/config/dns-maintenance.timer" \
        /etc/systemd/system/dns-maintenance.timer

    cp "$TMP_DIR/repository/config/healthcheck.service" \
        /etc/systemd/system/healthcheck.service

    cp "$TMP_DIR/repository/config/healthcheck.timer" \
        /etc/systemd/system/healthcheck.timer

    cp "$TMP_DIR/repository/config/nftables.service" \
        /etc/systemd/system/nftables.service



    cp "$TMP_DIR/repository/config/dns-access-logrotate" \
        /etc/logrotate.d/dns-access

    ok "Project files installed."
}

create_python_environments() {
    log "Creating Python environments..."

    python3 -m venv "$INSTALL_DIR/venv"
    python3 -m venv "$ADMIN_DIR/venv"

    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    "$ADMIN_DIR/venv/bin/pip" install --upgrade pip

    "$INSTALL_DIR/venv/bin/pip" install \
        -r "$TMP_DIR/repository/dns-access/requirements.txt"

    "$ADMIN_DIR/venv/bin/pip" install \
        -r "$TMP_DIR/repository/dns-admin/requirements.txt"

    ok "Python environments created."
}

generate_secrets() {
    log "Generating secrets..."

    FLASK_SECRET="$(openssl rand -hex 32)"

    LINK_ENCRYPTION_KEY="$(
        "$ADMIN_DIR/venv/bin/python" - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
    )"

    cat > /etc/dns-admin.env <<EOF
ADMIN_USER=$(printf '%s' "$ADMIN_USER")
ADMIN_PASSWORD_B64=$(printf '%s' "$ADMIN_PASSWORD" | base64 -w0)
FLASK_SECRET=$(printf '%s' "$FLASK_SECRET")
LINK_ENCRYPTION_KEY=$(printf '%s' "$LINK_ENCRYPTION_KEY")
EOF

    chmod 600 /etc/dns-admin.env

    ok "Secrets generated."
}

create_environment() {
    log "Creating runtime environment..."

    cat > /etc/dns-access.conf <<EOF
SERVER_IP=$SERVER_IP
IPV4_ENABLED=$IPV4_ENABLED
IPV6_ENABLED=$IPV6_ENABLED

DNS_ACCESS_HOST=0.0.0.0
DNS_ACCESS_PORT=8787

DNS_ADMIN_HOST=0.0.0.0
DNS_ADMIN_PORT=8790

DNS_RESOLVER_HOST=127.0.0.1
DNS_RESOLVER_PORT=5353
EOF

    chmod 600 /etc/dns-access.conf

    ok "Runtime environment created."
}

configure_unbound() {
    log "Configuring DNS resolver..."

    mkdir -p /etc/unbound /var/lib/unbound

    if [[ -f /usr/share/dns/root.hints ]]; then
        cp /usr/share/dns/root.hints /var/lib/unbound/root.hints
    else
        curl -fsSL \
            https://www.internic.net/domain/named.root \
            -o /var/lib/unbound/root.hints
    fi

    unbound-anchor -a /var/lib/unbound/root.key || true

    cp "$TMP_DIR/repository/config/unbound.conf" \
        /etc/unbound/unbound.conf

    rm -f /etc/unbound/unbound-forwarders.conf

    chown -R unbound:unbound /var/lib/unbound

    chown root:unbound /etc/unbound/unbound.conf
    chmod 640 /etc/unbound/unbound.conf

    mkdir -p /run/unbound
    chown unbound:unbound /run/unbound

    unbound-checkconf /etc/unbound/unbound.conf

    ok "DNS resolver configured."
}

download_adguard() {
    log "Installing DNS filtering service..."

    local arch
    local download_url

    arch="$(uname -m)"

    case "$arch" in
        x86_64)
            arch="amd64"
            ;;
        aarch64)
            arch="arm64"
            ;;
        armv7l)
            arch="armv7"
            ;;
        armv6l)
            arch="armv6"
            ;;
        i386|i686)
            arch="386"
            ;;
        *)
            die "Unsupported CPU architecture: $arch"
            ;;
    esac

    download_url="https://github.com/AdguardTeam/AdGuardHome/releases/download/${ADGUARD_VERSION}/AdGuardHome_linux_${arch}.tar.gz"

    [[ -n "$download_url" && "$download_url" != "null" ]] ||
        die "Could not find a compatible release."

    mkdir -p /opt/AdGuardHome

    curl -fsSL "$download_url" -o "$TMP_DIR/adguard.tar.gz"

    tar -xzf "$TMP_DIR/adguard.tar.gz" \
        -C "$TMP_DIR"

    local extracted
    extracted="$(find "$TMP_DIR" -maxdepth 1 -type d -name 'AdGuardHome*' | head -n 1)"

    [[ -n "$extracted" ]] || die "AdGuardHome archive extraction failed."

    cp "$extracted/AdGuardHome" \
        /opt/AdGuardHome/AdGuardHome

    chmod 755 /opt/AdGuardHome/AdGuardHome

    ok "DNS filtering service installed."
}

configure_adguard() {
    log "Configuring DNS filtering service..."

    mkdir -p /opt/AdGuardHome

    sed \
        -e "s|__SERVER_IP__|$SERVER_IP|g" \
        "$TMP_DIR/repository/config/AdGuardHome.yaml" \
        > /opt/AdGuardHome/AdGuardHome.yaml

    if [[ "$IPV6_ENABLED" == "true" ]]; then
        sed -i "s|__SERVER_IPV6__|$SERVER_IPV6|g" \
            /opt/AdGuardHome/AdGuardHome.yaml
    else
        sed -i '/^[[:space:]]*- "__SERVER_IPV6__"$/d' \
            /opt/AdGuardHome/AdGuardHome.yaml
    fi

    local adguard_hash

    adguard_hash="$(printf '%s\n' "$ADGUARD_PASSWORD" | htpasswd -nBi -C 10 "$ADGUARD_USER" | cut -d: -f2)"
    adguard_hash="${adguard_hash/\$2y\$/\$2a\$}"

    [[ "$adguard_hash" =~ ^\$2a\$ ]] || die "Could not generate a valid AdGuard password hash."

    python3 - "$ADGUARD_USER" "$adguard_hash" /opt/AdGuardHome/AdGuardHome.yaml <<'PYTHON'
import sys
from pathlib import Path

username, password_hash, filename = sys.argv[1:]
path = Path(filename)
content = path.read_text()

address = "  address: 127.0.0.1:8081"
users = "users: []"

if content.count(address) != 1:
    raise SystemExit("Unexpected AdGuard HTTP address configuration.")

if content.count(users) != 1:
    raise SystemExit("Unexpected AdGuard users configuration.")

content = content.replace(address, "  address: 0.0.0.0:8081")
content = content.replace(
    users,
    f'users:\n  - name: "{username}"\n    password: "{password_hash}"'
)

path.write_text(content)
PYTHON

    chmod 600 /opt/AdGuardHome/AdGuardHome.yaml

    # AdGuard Home v0.107.79 uses configuration schema version 34.
    printf '\nschema_version: 34\n' >> /opt/AdGuardHome/AdGuardHome.yaml

    /opt/AdGuardHome/AdGuardHome \
        --check-config \
        -c /opt/AdGuardHome/AdGuardHome.yaml \
        -w /opt/AdGuardHome || die "AdGuard Home configuration validation failed."

    cp "$TMP_DIR/repository/config/AdGuardHome.service" \
        /etc/systemd/system/AdGuardHome.service

    ok "DNS filtering configuration prepared."
}

configure_nftables() {
    log "Configuring firewall rules..."

    cp "$TMP_DIR/repository/config/nftables.conf" \
        /etc/dns-access/nftables.conf

    nft -c -f /etc/dns-access/nftables.conf

    ok "Firewall configuration validated."
}

enable_services() {
    log "Enabling services..."

    systemctl daemon-reload

    systemctl enable nftables.service
    systemctl enable unbound.service
    systemctl enable AdGuardHome.service
    systemctl enable dns-access.service
    systemctl enable dns-admin.service
    systemctl enable dns-maintenance.timer
    systemctl enable healthcheck.timer

    ok "Services enabled."
}

start_services() {
    log "Starting services..."

    systemctl restart nftables.service
    systemctl restart unbound.service
    systemctl restart AdGuardHome.service


    systemctl restart dns-access.service
    systemctl restart dns-admin.service

    systemctl start dns-maintenance.timer
    systemctl start healthcheck.timer

    ok "Services started."
}

run_initial_maintenance() {
    log "Running initial maintenance..."

    systemctl start dns-maintenance.service

    ok "Initial maintenance completed."
}

wait_for_app_ports() {
    log "Waiting for application ports..."

    for attempt in {1..15}; do
        if ss -lnt 2>/dev/null | grep -Eq "0\\.0\\.0\\.0:8787[[:space:]]" &&
           ss -lnt 2>/dev/null | grep -Eq "0\\.0\\.0\\.0:8790[[:space:]]"; then
            ok "Application ports are ready."
            return 0
        fi

        sleep 2
    done

    log "Application ports are not ready after 30 seconds. Running health check anyway."
}

run_healthcheck() {
    log "Running health check..."

    wait_for_app_ports

    if ! "$INSTALL_DIR/healthcheck.sh"; then
        die "Health check failed. Review the failed checks above before using this server."
    fi

    ok "Health check completed."
}

show_result() {
    echo
    echo "========================================"
    echo " Installation completed"
    echo "========================================"
    echo
    echo "Admin panel:"
    echo "http://$SERVER_IP:8790/admin/"
    echo
    echo "AdGuard panel:"
    echo "http://$SERVER_IP:8081"
    echo
    echo "AdGuard username:"
    echo "$ADGUARD_USER"
    echo
    echo "Access link endpoint:"
    echo "http://$SERVER_IP:8787/join/<token>"
    echo
    echo "DNS server:"
    echo "$SERVER_IP:53"
    echo
    echo "Administrator username:"
    echo "$ADMIN_USER"
    echo
    echo "The administrator password is the password entered during installation."
    echo
}

main() {
    require_root
    require_tty
    check_os
    ask_configuration

    install_packages
    prepare_directories
    download_project
    install_project_files
    create_python_environments
    generate_secrets
    create_environment

    configure_unbound
    download_adguard
    configure_adguard

    configure_nftables

    systemctl daemon-reload
    systemctl enable nftables.service
    systemctl restart nftables.service




    enable_services
    start_services

    run_initial_maintenance
    run_healthcheck

    show_result
}

main "$@"
