#!/usr/bin/env bash

set -euo pipefail

APP_NAME="dns-access"
INSTALL_DIR="/opt/dns-access"
ADMIN_DIR="/opt/dns-admin"
CONFIG_FILE="/etc/dns-access.conf"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

validate_ipv4() {
    local ip="$1"

    [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1

    IFS='.' read -r a b c d <<< "$ip"

    (( a <= 255 )) || return 1
    (( b <= 255 )) || return 1
    (( c <= 255 )) || return 1
    (( d <= 255 )) || return 1

    return 0
}

validate_domain() {
    local domain="$1"

    [[ "$domain" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || return 1
    [[ "$domain" == *.* ]] || return 1

    return 0
}

validate_email() {
    local email="$1"

    [[ "$email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]
}

detect_public_ipv4() {
    local ip=""

    if command -v curl >/dev/null 2>&1; then
        ip="$(curl -4 -fsS --max-time 5 https://api.ipify.org 2>/dev/null || true)"
    fi

    if [[ -z "$ip" ]] && command -v wget >/dev/null 2>&1; then
        ip="$(wget -4 -qO- --timeout=5 https://api.ipify.org 2>/dev/null || true)"
    fi

    echo "$ip"
}

check_dns_record() {
    local domain="$1"
    local expected_ip="$2"
    local resolved_ip=""

    if command -v dig >/dev/null 2>&1; then
        resolved_ip="$(dig +short A "$domain" | head -n1 | tr -d '[:space:]')"
    else
        resolved_ip="$(getent ahostsv4 "$domain" 2>/dev/null | awk 'NR==1 {print $1}')"
    fi

    [[ -n "$resolved_ip" ]] || return 1

    [[ "$resolved_ip" == "$expected_ip" ]]
}

clear

echo
echo "============================================================"
echo "                    DNS ACCESS INSTALLER"
echo "============================================================"
echo

if [[ "${EUID}" -ne 0 ]]; then
    error "Please run this installer as root."
fi

if [[ ! -f /etc/os-release ]]; then
    error "Cannot detect operating system."
fi

source /etc/os-release

if [[ "${ID:-}" != "ubuntu" ]]; then
    error "This installer currently supports Ubuntu only."
fi

success "Ubuntu detected: ${PRETTY_NAME}"

if ! command -v apt-get >/dev/null 2>&1; then
    error "apt-get is not available."
fi

echo
info "Checking internet connectivity..."

if ! curl -fsS --max-time 8 https://example.com >/dev/null 2>&1; then
    error "Internet connectivity check failed."
fi

success "Internet connectivity is available."

echo
echo "------------------------------------------------------------"
echo " Server configuration"
echo "------------------------------------------------------------"
echo

DETECTED_IP="$(detect_public_ipv4)"

if [[ -n "$DETECTED_IP" ]]; then
    read -r -p "Server public IPv4 [${DETECTED_IP}]: " SERVER_IP
    SERVER_IP="${SERVER_IP:-$DETECTED_IP}"
else
    read -r -p "Server public IPv4: " SERVER_IP
fi

validate_ipv4 "$SERVER_IP" || error "Invalid IPv4 address: $SERVER_IP"

while true; do
    read -r -p "Domain: " DOMAIN

    if validate_domain "$DOMAIN"; then
        break
    fi

    warning "Invalid domain."
done

while true; do
    read -r -p "Let's Encrypt email: " LE_EMAIL

    if validate_email "$LE_EMAIL"; then
        break
    fi

    warning "Invalid email address."
done

echo
echo "------------------------------------------------------------"
echo " Admin account"
echo "------------------------------------------------------------"
echo

read -r -p "Admin username [admin]: " ADMIN_USER
ADMIN_USER="${ADMIN_USER:-admin}"

if [[ ! "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,32}$ ]]; then
    error "Invalid admin username."
fi

while true; do
    read -r -s -p "Admin password: " ADMIN_PASSWORD
    echo

    if [[ ${#ADMIN_PASSWORD} -lt 8 ]]; then
        warning "Password must contain at least 8 characters."
        continue
    fi

    read -r -s -p "Confirm admin password: " ADMIN_PASSWORD_CONFIRM
    echo

    if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then
        warning "Passwords do not match."
        continue
    fi

    break
done

echo
echo "------------------------------------------------------------"
echo " Network configuration"
echo "------------------------------------------------------------"
echo

read -r -p "Enable IPv4 DNS? [Y/n]: " ENABLE_IPV4
ENABLE_IPV4="${ENABLE_IPV4:-Y}"

read -r -p "Enable IPv6 DNS? [y/N]: " ENABLE_IPV6
ENABLE_IPV6="${ENABLE_IPV6:-N}"

if [[ "$ENABLE_IPV4" =~ ^[Yy]$ ]]; then
    IPV4_ENABLED="true"
else
    IPV4_ENABLED="false"
fi

if [[ "$ENABLE_IPV6" =~ ^[Yy]$ ]]; then
    IPV6_ENABLED="true"
else
    IPV6_ENABLED="false"
fi

echo
echo "============================================================"
echo "                 INSTALLATION CONFIGURATION"
echo "============================================================"
echo
echo "Server IPv4       : $SERVER_IP"
echo "Domain            : $DOMAIN"
echo "Let's Encrypt     : $LE_EMAIL"
echo "Admin username    : $ADMIN_USER"
echo "IPv4 DNS          : $IPV4_ENABLED"
echo "IPv6 DNS          : $IPV6_ENABLED"
echo
echo "============================================================"
echo

read -r -p "Continue with installation? [Y/n]: " CONFIRM
CONFIRM="${CONFIRM:-Y}"

if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo
    warning "Installation cancelled."
    exit 0
fi

echo
echo "============================================================"
echo "                 INSTALLING PACKAGES"
echo "============================================================"
echo

export DEBIAN_FRONTEND=noninteractive

apt-get update

apt-get install -y \
    curl \
    wget \
    ca-certificates \
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
    sqlite3 \
    dnsutils \
    jq

success "Required packages installed."

echo
info "Checking domain DNS..."

if check_dns_record "$DOMAIN" "$SERVER_IP"; then
    success "Domain points to this server."
else
    warning "Domain does not currently resolve to $SERVER_IP."
    warning "Let's Encrypt may fail until the DNS record is correct."

    read -r -p "Continue anyway? [y/N]: " CONTINUE_DNS
    CONTINUE_DNS="${CONTINUE_DNS:-N}"

    if [[ ! "$CONTINUE_DNS" =~ ^[Yy]$ ]]; then
        error "Installation stopped. Point the domain to $SERVER_IP and run again."
    fi
fi

echo
info "Checking required ports..."

for port in 80 443 53; do
    if ss -lntup 2>/dev/null | grep -Eq ":${port}[[:space:]]"; then
        warning "Port $port is already in use."
    else
        success "Port $port is available."
    fi
done

echo
info "Creating application directories..."

mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/app"
mkdir -p "$INSTALL_DIR/data"

mkdir -p "$ADMIN_DIR"
mkdir -p "$ADMIN_DIR/app"

chmod 700 "$INSTALL_DIR"
chmod 700 "$ADMIN_DIR"

success "Application directories created."

echo
info "Saving installation configuration..."

cat > "$CONFIG_FILE" <<EOF
SERVER_IP="$SERVER_IP"
DOMAIN="$DOMAIN"
LE_EMAIL="$LE_EMAIL"
ADMIN_USER="$ADMIN_USER"
IPV4_ENABLED="$IPV4_ENABLED"
IPV6_ENABLED="$IPV6_ENABLED"
EOF

chmod 600 "$CONFIG_FILE"

success "Configuration saved to $CONFIG_FILE."

echo
info "Creating Python virtual environments..."

python3 -m venv "$INSTALL_DIR/venv"
python3 -m venv "$ADMIN_DIR/venv"

"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$ADMIN_DIR/venv/bin/pip" install --upgrade pip

success "Python environments created."

echo
info "Preparing service directories..."

mkdir -p /etc/dns-access
mkdir -p /etc/dns-access/ssl

chmod 700 /etc/dns-access
chmod 700 /etc/dns-access/ssl

echo
echo "============================================================"
echo "                 BASE INSTALLATION READY"
echo "============================================================"
echo
echo "Domain            : https://$DOMAIN"
echo "Server IPv4       : $SERVER_IP"
echo "Admin username    : $ADMIN_USER"
echo "IPv4 DNS          : $IPV4_ENABLED"
echo "IPv6 DNS          : $IPV6_ENABLED"
echo
echo "Prepared:"
echo
echo "  [OK] Ubuntu validation"
echo "  [OK] Internet check"
echo "  [OK] Interactive configuration"
echo "  [OK] Required packages"
echo "  [OK] Application directories"
echo "  [OK] Python environments"
echo "  [OK] Installation configuration"
echo
echo "Next installer components:"
echo
echo "  - TLS certificate"
echo "  - Nginx"
echo "  - Unbound"
echo "  - AdGuard Home"
echo "  - nftables"
echo "  - DNS access service"
echo "  - Admin panel"
echo "  - systemd services"
echo "  - User management commands"
echo
echo "============================================================"
echo

success "Base installer completed."
