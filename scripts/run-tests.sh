#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "========================================"
echo " DNS Access Project Tests"
echo "========================================"
echo

echo "[1/6] Checking project structure..."
"$SCRIPT_DIR/check-project.sh"

echo
echo "[2/6] Checking shell syntax..."
bash -n "$SCRIPT_DIR/../install.sh"
bash -n "$SCRIPT_DIR/prepare-directories.sh"
bash -n "$SCRIPT_DIR/check-requirements.sh"
bash -n "$SCRIPT_DIR/generate-secrets.sh"
bash -n "$SCRIPT_DIR/check-dns.sh"
bash -n "$SCRIPT_DIR/test-nginx.sh"
bash -n "$SCRIPT_DIR/test-unbound.sh"
bash -n "$SCRIPT_DIR/test-nftables.sh"
bash -n "$SCRIPT_DIR/test-services.sh"
bash -n "$SCRIPT_DIR/run-tests.sh"
bash -n "$SCRIPT_DIR/version.sh"
echo "[OK] Shell syntax"

echo
echo "[3/6] Checking Python syntax..."
python3 -m py_compile \
    "$SCRIPT_DIR/../dns-access/app.py" \
    "$SCRIPT_DIR/../dns-access/maintenance.py" \
    "$SCRIPT_DIR/../dns-admin/app.py"
echo "[OK] Python syntax"

echo
echo "[4/6] Testing nginx configuration..."
if [[ "${EUID}" -eq 0 && -x /usr/sbin/nginx && -f /etc/nginx/nginx.conf ]]; then
    "$SCRIPT_DIR/test-nginx.sh"
else
    echo "[SKIP] nginx runtime configuration is not available."
fi

echo
echo "[5/6] Testing Unbound configuration..."
if [[ "${EUID}" -eq 0 && -x /usr/sbin/unbound && -f /etc/unbound/unbound.conf ]]; then
    "$SCRIPT_DIR/test-unbound.sh"
else
    echo "[SKIP] Unbound runtime configuration is not available."
fi

echo
echo "[6/6] Testing nftables configuration..."
if [[ "${EUID}" -eq 0 && -x /usr/sbin/nft && -f /etc/dns-access/nftables.conf ]]; then
    "$SCRIPT_DIR/test-nftables.sh"
else
    echo "[SKIP] nftables runtime configuration is not available."
fi

echo
echo "========================================"
echo "[OK] Project tests completed."
echo "========================================"
