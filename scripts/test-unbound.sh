#!/usr/bin/env bash

set -euo pipefail

UNBOUND_BIN="/usr/sbin/unbound"
CONFIG="/etc/unbound/unbound.conf"

if [[ ! -x "$UNBOUND_BIN" ]]; then
    echo "[ERROR] unbound binary not found."
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "[ERROR] unbound configuration not found."
    exit 1
fi

echo "[INFO] Testing Unbound configuration..."

"$UNBOUND_BIN" \
    -c "$CONFIG" \
    -t

echo "[OK] Unbound configuration is valid."
