#!/usr/bin/env bash

set -euo pipefail

REPO_URL="https://github.com/Bad-Noob/dns-access.git"
ADGUARD_VERSION="v0.107.79"
RAW_BASE_URL="https://raw.githubusercontent.com/Bad-Noob/dns-access/main"

DOH_ENABLED="false"
DOH_DOMAIN=""
DOH_EMAIL=""

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

    echo
    echo "DNS over HTTPS (DoH):"
    echo "1) Disabled (default)"
    echo "2) Enabled"

    read -r -p "Choose [1]: " DOH_CHOICE </dev/tty
    DOH_CHOICE="${DOH_CHOICE:-1}"

    case "$DOH_CHOICE" in
        1)
            DOH_ENABLED="false"
            ;;
        2)
            DOH_ENABLED="true"
            DOH_DOMAIN="$(ask_value "DoH domain name")"
            DOH_DOMAIN="${DOH_DOMAIN,,}"

            while [[ ! "$DOH_DOMAIN" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]] || (( ${#DOH_DOMAIN} > 253 )); do
                echo "Invalid domain name."
                DOH_DOMAIN="$(ask_value "DoH domain name")"
                DOH_DOMAIN="${DOH_DOMAIN,,}"
            done

            DOH_EMAIL="$(ask_value "Let's Encrypt email (optional)")"
            ;;
        *)
            die "Invalid DoH option."
            ;;
    esac

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
    echo "DoH         : $DOH_ENABLED"
    if [[ "$DOH_ENABLED" == "true" ]]; then
        echo "DoH domain  : $DOH_DOMAIN"
    fi
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

configure_doh() {
    if [[ "$DOH_ENABLED" != "true" ]]; then
        log "DNS over HTTPS is disabled."
        return 0
    fi

    log "Configuring DNS over HTTPS..."

    local config_file="/opt/AdGuardHome/AdGuardHome.yaml"
    local config_backup="${config_file}.pre-doh"
    local cert_dir="/etc/letsencrypt/live/${DOH_DOMAIN}"
    local hook_file="/etc/letsencrypt/renewal-hooks/deploy/reload-adguardhome.sh"

    if ! command -v ss >/dev/null 2>&1; then
        die "The ss command is required to check network ports."
    fi

    if ss -H -ltn 'sport = :80' | grep -q .; then
        die "TCP port 80 is already in use. Free it before enabling DoH."
    fi

    if ss -H -ltn 'sport = :443' | grep -q .; then
        die "TCP port 443 is already in use. Free it before enabling DoH."
    fi

    if ! command -v dig >/dev/null 2>&1; then
        if ! apt-get update; then
            die "Package index update failed while installing dnsutils."
        fi

        if ! DEBIAN_FRONTEND=noninteractive apt-get install -y dnsutils; then
            die "Could not install dnsutils."
        fi
    fi

    local resolved_ipv4
    resolved_ipv4="$(dig +short A "$DOH_DOMAIN" @1.1.1.1 | grep -E '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' | sort -u || true)"

    if [[ -z "$resolved_ipv4" ]]; then
        die "No IPv4 A record was found for ${DOH_DOMAIN}."
    fi

    if [[ "$resolved_ipv4" != "$SERVER_IP" ]]; then
        die "The A record for ${DOH_DOMAIN} must point only to ${SERVER_IP}. Found: ${resolved_ipv4}"
    fi

    local resolved_ipv6
    resolved_ipv6="$(dig +short AAAA "$DOH_DOMAIN" @1.1.1.1 | grep -E '^[0-9A-Fa-f:]+$' | sort -u || true)"

    if [[ -n "$resolved_ipv6" ]]; then
        if [[ "$IPV6_ENABLED" != "true" || -z "$SERVER_IPV6" ]]; then
            die "The domain has an AAAA record, but IPv6 is not enabled for this server. Remove the AAAA record or enable IPv6."
        fi

        if ! python3 - "$SERVER_IPV6" "$resolved_ipv6" <<'PYTHON'
import ipaddress
import sys

try:
    expected = ipaddress.IPv6Address(sys.argv[1])
    records = [
        ipaddress.IPv6Address(value.strip())
        for value in sys.argv[2].splitlines()
        if value.strip()
    ]
except ValueError as exc:
    print(f"Invalid IPv6 address: {exc}", file=sys.stderr)
    sys.exit(1)

if len(records) != 1 or records[0] != expected:
    print(
        f"AAAA records must contain only the server IPv6 address ({expected}). "
        f"Found: {', '.join(str(value) for value in records)}",
        file=sys.stderr,
    )
    sys.exit(1)
PYTHON
        then
            die "The AAAA record does not match the server IPv6 address."
        fi
    fi

    if [[ ! -f "$config_file" ]]; then
        die "AdGuard Home configuration file was not found: ${config_file}"
    fi

    if grep -Eq '^tls:' "$config_file"; then
        die "The AdGuard Home configuration already contains a top-level TLS section. Refusing to overwrite it."
    fi

    if [[ -e "$config_backup" ]]; then
        die "An existing DoH configuration backup was found: ${config_backup}"
    fi

    if [[ -e "$hook_file" ]]; then
        die "An existing AdGuard Home renewal hook was found: ${hook_file}"
    fi

    local certbot_timer_enabled=""
    local certbot_timer_active=""
    local hook_tmp=""
    local adguard_was_active="false"

    certbot_timer_enabled="$(systemctl is-enabled certbot.timer 2>/dev/null || true)"
    certbot_timer_active="$(systemctl is-active certbot.timer 2>/dev/null || true)"

    if systemctl is-active --quiet AdGuardHome; then
        adguard_was_active="true"
    fi

    rollback_doh() {
        if [[ -f "$config_backup" ]]; then
            if ! cp -a "$config_backup" "$config_file"; then
                error "Could not restore the original AdGuard Home configuration."
            elif [[ "$adguard_was_active" == "true" ]]; then
                systemctl restart AdGuardHome || error "Could not restart AdGuard Home after configuration rollback."
            fi
        fi

        if [[ -n "$hook_tmp" ]]; then
            rm -f -- "$hook_tmp" || error "Could not remove the temporary renewal hook."
        fi

        rm -f -- "$hook_file" || error "Could not remove the renewal hook."

        if systemctl cat certbot.timer >/dev/null 2>&1; then
            case "$certbot_timer_enabled" in
                enabled)
                    systemctl enable certbot.timer || error "Could not restore the enabled state of certbot.timer."
                    ;;
                enabled-runtime)
                    systemctl enable --runtime certbot.timer || error "Could not restore the runtime-enabled state of certbot.timer."
                    ;;
                disabled)
                    systemctl disable certbot.timer || error "Could not restore the disabled state of certbot.timer."
                    ;;
                masked)
                    systemctl mask certbot.timer || error "Could not restore the masked state of certbot.timer."
                    ;;
                masked-runtime)
                    systemctl mask --runtime certbot.timer || error "Could not restore the runtime-masked state of certbot.timer."
                    ;;
                not-found)
                    systemctl disable certbot.timer || error "Could not disable the newly installed certbot.timer."
                    ;;
            esac

            case "$certbot_timer_active" in
                active)
                    systemctl start certbot.timer || error "Could not restore the active state of certbot.timer."
                    ;;
                inactive|failed|unknown)
                    if systemctl is-active --quiet certbot.timer; then
                        systemctl stop certbot.timer || error "Could not restore the inactive state of certbot.timer."
                    fi
                    ;;
            esac
        fi
    }

    if ! apt-get update; then
        rollback_doh
        die "Package index update failed."
    fi

    if ! DEBIAN_FRONTEND=noninteractive apt-get install -y certbot; then
        rollback_doh
        die "Certbot installation failed. Previous timer state was restored where possible."
    fi

    local certbot_args=(
        certonly
        --standalone
        --non-interactive
        --agree-tos
        --no-eff-email
        --preferred-challenges http
        -d "$DOH_DOMAIN"
    )

    if [[ -n "$DOH_EMAIL" ]]; then
        certbot_args+=(--email "$DOH_EMAIL")
    else
        certbot_args+=(--register-unsafely-without-email)
    fi

    if ! certbot "${certbot_args[@]}"; then
        rollback_doh
        die "Certificate issuance failed. Previous timer state was restored where possible."
    fi

    if [[ ! -s "${cert_dir}/fullchain.pem" || ! -s "${cert_dir}/privkey.pem" ]]; then
        rollback_doh
        die "Let's Encrypt certificate files were not found. Previous timer state was restored where possible."
    fi

    if [[ ! -f "$config_file" ]]; then
        rollback_doh
        die "AdGuard Home configuration file was not found: ${config_file}"
    fi

    if grep -Eq '^tls:' "$config_file"; then
        rollback_doh
        die "The AdGuard Home configuration already contains a top-level TLS section. Refusing to overwrite it."
    fi

    if ! cp -a "$config_file" "$config_backup"; then
        rm -f -- "$config_backup"
        rollback_doh
        die "Could not back up the original AdGuard Home configuration."
    fi


    if ! cat >> "$config_file" <<EOF

tls:
  enabled: true
  server_name: "${DOH_DOMAIN}"
  force_https: false
  port_https: 443
  port_dns_over_tls: 0
  port_dns_over_quic: 0
  certificate_path: "${cert_dir}/fullchain.pem"
  private_key_path: "${cert_dir}/privkey.pem"
EOF
    then
        rollback_doh
        die "Could not write the DoH configuration. The original configuration was restored."
    fi

    if ! chmod 600 "$config_file"; then
        rollback_doh
        die "Could not secure the AdGuard Home configuration file."
    fi

    if ! /opt/AdGuardHome/AdGuardHome --check-config -c "$config_file" -w /opt/AdGuardHome; then
        rollback_doh
        die "AdGuard Home rejected the DoH configuration. The original configuration was restored."
    fi

    if ! install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy; then
        rollback_doh
        die "Could not create the Certbot deploy hook directory."
    fi

    hook_tmp="$(mktemp "${hook_file}.XXXXXX")" || {
        rollback_doh
        die "Could not create a temporary renewal hook."
    }

    if ! cat > "$hook_tmp" <<'EOF'
#!/bin/sh
set -eu
systemctl restart AdGuardHome
EOF
    then
        rollback_doh
        die "Could not write the Certbot renewal hook."
    fi

    if ! chmod 750 "$hook_tmp" || ! mv "$hook_tmp" "$hook_file"; then
        rollback_doh
        die "Could not install the Certbot renewal hook."
    fi

    hook_tmp=""

    if ! systemctl enable --now certbot.timer; then
        rollback_doh
        die "Could not enable the Certbot renewal timer. The original AdGuard Home configuration was restored."
    fi

    unset -f rollback_doh

    ok "DNS over HTTPS configuration completed."
    log "DoH endpoint: https://${DOH_DOMAIN}/dns-query"
    log "Keep inbound TCP port 443 available. TCP port 80 is required for certificate issuance and renewal."
}

test_doh() {
    if [[ "$DOH_ENABLED" != "true" ]]; then
        return 0
    fi

    log "Testing DNS over HTTPS..."

    python3 - "$DOH_DOMAIN" <<'PYTHON'
import secrets
import struct
import sys
import urllib.request

domain = sys.argv[1]
query_name = "example.com"
request_id = secrets.randbelow(65536)

labels = query_name.split(".")
encoded_name = b"".join(bytes([len(label)]) + label.encode("ascii") for label in labels) + b"\x00"
question = encoded_name + struct.pack("!HH", 1, 1)
packet = struct.pack("!HHHHHH", request_id, 0x0100, 1, 0, 0, 0) + question

url = f"https://{domain}/dns-query"
request = urllib.request.Request(
    url,
    data=packet,
    headers={
        "Content-Type": "application/dns-message",
        "Accept": "application/dns-message",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=15) as response:
        status = response.status
        content_type = response.headers.get("Content-Type", "").lower()
        body = response.read()
except Exception as exc:
    print(f"DoH request failed: {exc}", file=sys.stderr)
    sys.exit(1)

if status != 200:
    raise SystemExit(f"Unexpected HTTP status: {status}")

if "application/dns-message" not in content_type:
    raise SystemExit(f"Unexpected content type: {content_type}")

if len(body) < 12:
    raise SystemExit("DNS response is too short.")

response_id, flags, questions, answers, _, _ = struct.unpack("!HHHHHH", body[:12])

if response_id != request_id:
    raise SystemExit("DNS response ID does not match the request.")

if not (flags & 0x8000):
    raise SystemExit("The DNS response flag is not set.")

if (flags & 0x000F) != 0:
    raise SystemExit(f"DNS response returned error code {(flags & 0x000F)}.")

if questions != 1 or answers < 1:
    raise SystemExit(f"Unexpected DNS response: questions={questions}, answers={answers}.")

print(f"DoH test passed: HTTP {status}, DNS answers={answers}, response size={len(body)} bytes.")
PYTHON

    ok "DNS over HTTPS test passed."
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
    if [[ "$DOH_ENABLED" == "true" ]]; then
        echo "DNS over HTTPS:"
        echo "https://$DOH_DOMAIN/dns-query"
        echo
    fi
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
    configure_doh

    configure_nftables

    systemctl daemon-reload
    systemctl enable nftables.service
    systemctl restart nftables.service




    enable_services
    start_services
    test_doh

    run_initial_maintenance
    run_healthcheck

    show_result
}

main "$@"
