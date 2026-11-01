#!/usr/bin/env bash

set -euo pipefail

CHECK_BIN="/usr/sbin/unbound-checkconf"
CONFIG="/etc/unbound/unbound.conf"

if [[ ! -x "$CHECK_BIN" ]]; then
    echo "[ERROR] unbound-checkconf not found."
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "[ERROR] Unbound configuration not found."
    exit 1
fi

echo "[INFO] Testing Unbound configuration..."

"$CHECK_BIN" "$CONFIG"

echo "[OK] Unbound configuration is valid."
