#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================"
echo " DNS Access Project Tests"
echo "========================================"
echo

echo "[1/8] Checking project structure..."
"$SCRIPT_DIR/check-project.sh"

echo
echo "[2/8] Checking shell syntax..."

while IFS= read -r script; do
    bash -n "$script"
done < <(find "$ROOT_DIR" -type f -name "*.sh" -print)

echo "[OK] Shell syntax"

echo
echo "[3/8] Checking Python syntax..."

python3 -m py_compile \
    "$ROOT_DIR/dns-access/app.py" \
    "$ROOT_DIR/dns-access/maintenance.py" \
    "$ROOT_DIR/dns-admin/app.py"

echo "[OK] Python syntax"

echo
echo "[4/8] Checking required Python modules..."

python3 - <<'PY'
import importlib.util
import sys

required = [
    "cryptography",
    "flask",
]

missing = [
    module
    for module in required
    if importlib.util.find_spec(module) is None
]

if missing:
    print("[SKIP] Missing modules:", ", ".join(missing))
    print("[INFO] Runtime virtual environments install these dependencies.")
else:
    print("[OK] Required Python modules are available.")
PY

echo
echo "[5/8] Checking version..."

"$SCRIPT_DIR/version.sh"

echo "[OK] Version"

echo
echo "[6/8] Testing nginx configuration..."

if [[ "${EUID}" -eq 0 && -x /usr/sbin/nginx && -f /etc/nginx/nginx.conf ]]; then
    "$SCRIPT_DIR/test-nginx.sh"
else
    echo "[SKIP] nginx runtime configuration is not available."
fi

echo
echo "[7/8] Testing Unbound configuration..."

if [[ "${EUID}" -eq 0 && -x /usr/sbin/unbound-checkconf && -f /etc/unbound/unbound.conf ]]; then
    "$SCRIPT_DIR/test-unbound.sh"
else
    echo "[SKIP] Unbound runtime configuration is not available."
fi

echo
echo "[8/8] Testing nftables configuration..."

if [[ "${EUID}" -eq 0 && -x /usr/sbin/nft && -f /etc/dns-access/nftables.conf ]]; then
    "$SCRIPT_DIR/test-nftables.sh"
else
    echo "[SKIP] nftables runtime configuration is not available."
fi

echo
echo "========================================"
echo "[OK] Project tests completed."
echo "========================================"
