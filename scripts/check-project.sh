#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

REQUIRED_FILES=(
    "install.sh"
    "VERSION"
    "README.md"
    "LICENSE"

    "dns-access/app.py"
    "dns-access/maintenance.py"
    "dns-access/healthcheck.sh"
    "dns-access/requirements.txt"
    "dns-access/Makefile"
    "dns-access/__init__.py"

    "dns-admin/app.py"
    "dns-admin/requirements.txt"
    "dns-admin/__init__.py"

    "scripts/prepare-directories.sh"
    "scripts/check-requirements.sh"
    "scripts/generate-secrets.sh"
    "scripts/check-dns.sh"
    "scripts/test-nginx.sh"
    "scripts/test-unbound.sh"
    "scripts/test-nftables.sh"
    "scripts/test-services.sh"
    "scripts/run-tests.sh"
    "scripts/version.sh"

    "config/AdGuardHome.service"
    "config/AdGuardHome.yaml"
    "config/certbot-renew.service"
    "config/certbot-renew.timer"
    "config/dns-access.conf"
    "config/dns-access.env"
    "config/dns-access.service"
    "config/dns-access-logrotate"
    "config/dns-access-logrotate.service"
    "config/dns-access-logrotate.timer"
    "config/dns-access-security.conf"
    "config/dns-admin.env"
    "config/dns-admin.service"
    "config/dns-allow.conf"
    "config/dns-maintenance.service"
    "config/dns-maintenance.timer"
    "config/healthcheck.service"
    "config/healthcheck.timer"
    "config/defaults.conf"
    "config/certbot-webroot.conf"
    "config/limits.conf"
    "config/logrotate.conf"
    "config/nginx.conf"
    "config/nftables.conf"
    "config/nftables.service"
    "config/tmpfiles.conf"
    "config/unbound.conf"
    "config/unbound-forwarders.conf"
    "config/unbound-forwarders-direct.conf"
    "config/unbound.service"
    "config/README.md"
)

FAILED=0

echo "========================================"
echo " DNS Access Project Structure"
echo "========================================"
echo

for file in "${REQUIRED_FILES[@]}"; do
    if [[ -f "$ROOT_DIR/$file" ]]; then
        printf '[OK]   %s\n' "$file"
    else
        printf '[FAIL] %s\n' "$file"
        FAILED=$((FAILED + 1))
    fi
done

echo

if [[ "$FAILED" -gt 0 ]]; then
    echo "[ERROR] Missing $FAILED required file(s)."
    exit 1
fi

echo "[OK] Project structure is complete."
