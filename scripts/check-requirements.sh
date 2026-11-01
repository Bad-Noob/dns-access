#!/usr/bin/env bash

set -euo pipefail

fail() {
    echo "[ERROR] $1"
    exit 1
}

ok() {
    echo "[OK] $1"
}

if [[ "${EUID}" -ne 0 ]]; then
    fail "This script must be run as root."
fi

if [[ ! -f /etc/os-release ]]; then
    fail "Cannot detect operating system."
fi

source /etc/os-release

if [[ "${ID:-}" != "ubuntu" ]]; then
    fail "Ubuntu is required."
fi

ok "Ubuntu detected: ${PRETTY_NAME}"

REQUIRED_COMMANDS=(
    apt-get
    curl
    wget
    git
    python3
    openssl
    sqlite3
    systemctl
    nft
    nginx
    unbound-checkconf
)

FAILED=0

for command in "${REQUIRED_COMMANDS[@]}"; do
    if command -v "$command" >/dev/null 2>&1; then
        ok "$command"
    else
        echo "[MISSING] $command"
        FAILED=$((FAILED + 1))
    fi
done

if [[ ! -d /proc ]]; then
    fail "/proc is not available."
fi

if [[ ! -d /sys ]]; then
    fail "/sys is not available."
fi

if [[ "$FAILED" -gt 0 ]]; then
    echo
    echo "[ERROR] Missing $FAILED required command(s)."
    echo "Run the installer first to install the required packages."
    exit 1
fi

echo
echo "[OK] All required system commands are available."
