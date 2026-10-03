#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================"
echo " DNS Access Project Tests"
echo "========================================"
echo

echo "[1/7] Checking project structure..."
"$SCRIPT_DIR/check-project.sh"

echo
echo "[2/7] Checking shell syntax..."

while IFS= read -r script; do
    bash -n "$script"
done < <(find "$ROOT_DIR" -type f -name "*.sh" -print)

echo "[OK] Shell syntax"

echo
echo "[3/7] Checking Python syntax..."

python3 -m py_compile \
    "$ROOT_DIR/dns-access/app.py" \
    "$ROOT_DIR/dns-access/maintenance.py" \
    "$ROOT_DIR/dns-admin/app.py"

echo "[OK] Python syntax"

echo
echo "[4/7] Checking version..."

"$SCRIPT_DIR/version.sh"

echo "[OK] Version"

echo
echo "[5/7] Testing nginx configuration..."

if [[ "${EUID}" -eq 0 && -x /usr/sbin/nginx && -f /etc/nginx/nginx.conf ]]; then
    "$SCRIPT_DIR/test-nginx.sh"
else
    echo "[SKIP] nginx runtime configuration is not available."
fi

echo
echo "[6/7] Testing Unbound configuration..."

if [[ "${EUID}" -eq 0 && -x /usr/sbin/unbound-checkconf && -f /etc/unbound/unbound.conf ]]; then
    "$SCRIPT_DIR/test-unbound.sh"
else
    echo "[SKIP] Unbound runtime configuration is not available."
fi

echo
echo "[7/7] Testing nftables configuration..."

if [[ "${EUID}" -eq 0 && -x /usr/sbin/nft && -f /etc/dns-access/nftables.conf ]]; then
    "$SCRIPT_DIR/test-nftables.sh"
else
    echo "[SKIP] nftables runtime configuration is not available."
fi

echo
echo "========================================"
echo "[OK] Project tests completed."
echo "========================================"
