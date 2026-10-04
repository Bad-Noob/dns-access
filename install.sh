#!/usr/bin/env bash

set -euo pipefail

REPO_URL="https://github.com/Bad-Noob/dns-access.git"
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
        python3 \
        python3-venv \
        python3-pip \
        nginx \
        nftables \
        certbot \
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
        read -r -p "$prompt [$default_value]: " value
        value="${value:-$default_value}"
    else
        read -r -p "$prompt: " value
    fi

    printf '%s' "$value"
}

ask_password() {
    local prompt="$1"
    local password
    local confirm

    while true; do
        read -r -s -p "$prompt: " password
        echo
        read -r -s -p "Confirm password: " confirm
        echo

        [[ "$password" == "$confirm" ]] || {
            echo "Passwords do not match."
            continue
        }

        [[ "${#password}" -ge 12 ]] || {
            echo "Password must contain at least 12 characters."
            continue
        }

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

validate_domain() {
    local domain="$1"

    [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || return 1
    [[ "$domain" == *.* ]] || return 1
}

validate_email() {
    local email="$1"

    [[ "$email" =~ ^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$ ]]
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

    DOMAIN="$(ask_value "Domain")"

    while ! validate_domain "$DOMAIN"; do
        echo "Invalid domain."
        DOMAIN="$(ask_value "Domain")"
    done

    LE_EMAIL="$(ask_value "Let's Encrypt email")"

    while ! validate_email "$LE_EMAIL"; do
        echo "Invalid email address."
        LE_EMAIL="$(ask_value "Let's Encrypt email")"
    done

    ADMIN_USER="$(ask_value "Administrator username" "admin")"

    while [[ ! "$ADMIN_USER" =~ ^[a-zA-Z0-9._-]{3,32}$ ]]; do
        echo "Invalid administrator username."
        ADMIN_USER="$(ask_value "Administrator username" "admin")"
    done

    ADMIN_PASSWORD="$(ask_password "Administrator password")"

    echo
    echo "IPv4 DNS support:"
    echo "1) Enabled"
    echo "2) Disabled"

    read -r -p "Choose [1]: " IPV4_CHOICE
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

    read -r -p "Choose [2]: " IPV6_CHOICE
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

    echo
    echo "DNS upstream mode:"
    echo "1) Recursive DNS"
    echo "2) DNS over TLS"
    echo "3) Plain DNS"

    read -r -p "Choose [1]: " DNS_MODE_CHOICE
    DNS_MODE_CHOICE="${DNS_MODE_CHOICE:-1}"

    case "$DNS_MODE_CHOICE" in
        1)
            DNS_UPSTREAM_MODE="recursive"
            DNS_UPSTREAM_1=""
            DNS_UPSTREAM_2=""
            ;;
        2)
            DNS_UPSTREAM_MODE="dot"

            DNS_UPSTREAM_1="$(ask_value "First DNS over TLS upstream" "1.1.1.1@853#cloudflare-dns.com")"
            DNS_UPSTREAM_2="$(ask_value "Second DNS over TLS upstream" "1.0.0.1@853#cloudflare-dns.com")"
            ;;
        3)
            DNS_UPSTREAM_MODE="plain"

            DNS_UPSTREAM_1="$(ask_value "First DNS upstream" "1.1.1.1")"
            DNS_UPSTREAM_2="$(ask_value "Second DNS upstream" "9.9.9.9")"
            ;;
        *)
            die "Invalid DNS upstream option."
            ;;
    esac

    echo
    echo "========================================"
    echo " Configuration Summary"
    echo "========================================"
    echo
    echo "Public IPv4 : $SERVER_IP"
    echo "Public IPv6 : ${SERVER_IPV6:-disabled}"
    echo "Domain      : $DOMAIN"
    echo "LE email    : $LE_EMAIL"
    echo "Admin user  : $ADMIN_USER"
    echo "IPv4 DNS    : $IPV4_ENABLED"
    echo "IPv6 DNS    : $IPV6_ENABLED"
    echo "DNS mode    : $DNS_UPSTREAM_MODE"
    echo "Upstream 1  : ${DNS_UPSTREAM_1:-not used}"
    echo "Upstream 2  : ${DNS_UPSTREAM_2:-not used}"
    echo

    read -r -p "Continue installation? [y/N]: " CONFIRM

    [[ "$CONFIRM" =~ ^[Yy]$ ]] || die "Installation cancelled."
}

prepare_directories() {
    log "Preparing directories..."

    mkdir -p \
        "$INSTALL_DIR/app" \
        "$INSTALL_DIR/data" \
        "$ADMIN_DIR/app" \
        "$CONFIG_DIR/ssl" \
        /var/log/dns-access \
        /var/log/dns-admin \
        /var/www/certbot

    chmod 700 "$INSTALL_DIR"
    chmod 700 "$INSTALL_DIR/data"
    chmod 700 "$ADMIN_DIR"
    chmod 700 "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR/ssl"

    chmod 750 /var/log/dns-access
    chmod 750 /var/log/dns-admin

    ok "Directories prepared."
}

download_project() {
    log "Downloading project files..."

    git clone --depth 1 "$REPO_URL" "$TMP_DIR/repository"

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

    cp "$TMP_DIR/repository/config/certbot-renew.service" \
        /etc/systemd/system/certbot-renew.service

    cp "$TMP_DIR/repository/config/certbot-renew.timer" \
        /etc/systemd/system/certbot-renew.timer

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
ADMIN_PASSWORD=$(printf '%s' "$ADMIN_PASSWORD")
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
DOMAIN=$DOMAIN
LE_EMAIL=$LE_EMAIL

IPV4_ENABLED=$IPV4_ENABLED
IPV6_ENABLED=$IPV6_ENABLED

DNS_UPSTREAM_MODE=$DNS_UPSTREAM_MODE
DNS_UPSTREAM_1=$DNS_UPSTREAM_1
DNS_UPSTREAM_2=$DNS_UPSTREAM_2

DOH_ENABLED=true
DOT_ENABLED=false
DOQ_ENABLED=false

DNS_ACCESS_HOST=127.0.0.1
DNS_ACCESS_PORT=8787

DNS_ADMIN_HOST=127.0.0.1
DNS_ADMIN_PORT=8790

DNS_RESOLVER_HOST=127.0.0.1
DNS_RESOLVER_PORT=5353

DNS_HTTPS_PORT=4443
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

    case "$DNS_UPSTREAM_MODE" in
        recursive)
            rm -f /etc/unbound/unbound-forwarders.conf
            ;;
        dot)
            sed \
                -e "s|__DNS_UPSTREAM_1__|$DNS_UPSTREAM_1|g" \
                -e "s|__DNS_UPSTREAM_2__|$DNS_UPSTREAM_2|g" \
                "$TMP_DIR/repository/config/unbound-forwarders.conf" \
                > /etc/unbound/unbound-forwarders.conf

            cat >> /etc/unbound/unbound.conf <<'EOF'

include: "/etc/unbound/unbound-forwarders.conf"
EOF
            ;;
        plain)
            sed \
                -e "s|__DNS_UPSTREAM_1__|$DNS_UPSTREAM_1|g" \
                -e "s|__DNS_UPSTREAM_2__|$DNS_UPSTREAM_2|g" \
                "$TMP_DIR/repository/config/unbound-forwarders-direct.conf" \
                > /etc/unbound/unbound-forwarders.conf

            cat >> /etc/unbound/unbound.conf <<'EOF'

include: "/etc/unbound/unbound-forwarders.conf"
EOF
            ;;
    esac

    chown -R unbound:unbound /var/lib/unbound
    chmod 640 /etc/unbound/unbound.conf

    unbound-checkconf /etc/unbound/unbound.conf

    ok "DNS resolver configured."
}

download_adguard() {
    log "Installing DNS filtering service..."

    local arch
    local release_json
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

    release_json="$(
        curl -fsSL \
            https://api.github.com/repos/AdguardTeam/AdGuardHome/releases/latest
    )"

    download_url="$(
        printf '%s' "$release_json" |
        jq -r --arg arch "$arch" '
            .assets[]
            | select(.name | test("AdGuardHome_linux_" + $arch + "_.*\\.tar\\.gz$"))
            | .browser_download_url
        ' |
        head -n 1
    )"

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

    local certificate="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    local private_key="/etc/letsencrypt/live/$DOMAIN/privkey.pem"

    sed \
        -e "s|__DOMAIN__|$DOMAIN|g" \
        -e "s|__SSL_CERT__|$certificate|g" \
        -e "s|__SSL_KEY__|$private_key|g" \
        "$TMP_DIR/repository/config/AdGuardHome.yaml" \
        > /opt/AdGuardHome/AdGuardHome.yaml

    cp "$TMP_DIR/repository/config/AdGuardHome.service" \
        /etc/systemd/system/AdGuardHome.service

    ok "DNS filtering configuration prepared."
}

configure_nginx() {
    log "Configuring web server..."

    mkdir -p /etc/nginx

    local certificate="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    local private_key="/etc/letsencrypt/live/$DOMAIN/privkey.pem"

    cp "$TMP_DIR/repository/config/dns-access-security.conf" \
        /etc/nginx/dns-access-security.conf

    printf 'deny all;\n' > /etc/nginx/dns-allow.conf

    sed \
        -e "s|__DOMAIN__|$DOMAIN|g" \
        -e "s|__SSL_CERT__|$certificate|g" \
        -e "s|__SSL_KEY__|$private_key|g" \
        "$TMP_DIR/repository/config/nginx.conf" \
        > /etc/nginx/conf.d/dns-access.conf

    if [[ "$IPV6_ENABLED" != "true" ]]; then
        sed -i '/listen \[::\]:80;/d' \
            /etc/nginx/conf.d/dns-access.conf

        sed -i '/listen \[::\]:443 ssl;/d' \
            /etc/nginx/conf.d/dns-access.conf
    fi


    ok "Web server configuration prepared."
}

issue_certificate() {
    log "Requesting Let's Encrypt certificate..."

    systemctl stop nginx || true

    mkdir -p /var/www/certbot

    certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email "$LE_EMAIL" \
        --domain "$DOMAIN"

    ok "TLS certificate obtained."
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
    systemctl enable nginx.service
    systemctl enable dns-access.service
    systemctl enable dns-admin.service
    systemctl enable dns-maintenance.timer
    systemctl enable healthcheck.timer
    systemctl enable certbot-renew.timer

    ok "Services enabled."
}

start_services() {
    log "Starting services..."

    systemctl restart nftables.service

    systemctl restart unbound.service

    systemctl restart AdGuardHome.service

    nginx -t
    systemctl restart nginx.service

    systemctl restart dns-access.service
    systemctl restart dns-admin.service

    systemctl start dns-maintenance.timer
    systemctl start healthcheck.timer
    systemctl start certbot-renew.timer

    ok "Services started."
}

run_initial_maintenance() {
    log "Running initial maintenance..."

    systemctl start dns-maintenance.service || true

    ok "Initial maintenance completed."
}

run_healthcheck() {
    log "Running health check..."

    "$INSTALL_DIR/healthcheck.sh"

    ok "Health check completed."
}

show_result() {
    echo
    echo "========================================"
    echo " Installation completed"
    echo "========================================"
    echo
    echo "Admin panel:"
    echo "https://$DOMAIN/admin/"
    echo
    echo "Access link endpoint:"
    echo "https://$DOMAIN/join/<token>"
    echo
    echo "DNS over HTTPS:"
    echo "https://$DOMAIN/dns-query"
    echo
    echo "Administrator username:"
    echo "$ADMIN_USER"
    echo
    echo "The administrator password is the password entered during installation."
    echo
}

main() {
    require_root
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

    configure_nginx

    issue_certificate

    nginx -t

    enable_services
    start_services

    run_initial_maintenance
    run_healthcheck

    show_result
}

main "$@"
