#!/usr/bin/env bash

set -euo pipefail

NGINX_BIN="/usr/sbin/nginx"

if [[ ! -x "$NGINX_BIN" ]]; then
    echo "[ERROR] nginx binary not found."
    exit 1
fi

echo "[INFO] Testing nginx configuration..."

"$NGINX_BIN" -t

echo "[OK] nginx configuration is valid."
