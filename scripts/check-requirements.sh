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

for command in \
    apt-get \
    curl \
    wget \
    python3 \
    systemctl \
    nft \
    nginx \
    openssl \
    sqlite3
do
    if command -v "$command" >/dev/null 2>&1; then
        ok "$command"
    else
        echo "[WARN] Missing command: $command"
    fi
done

if [[ ! -d /proc ]]; then
    fail "/proc is not available."
fi

if [[ ! -d /sys ]]; then
    fail "/sys is not available."
fi

echo
echo "Requirement check completed."
