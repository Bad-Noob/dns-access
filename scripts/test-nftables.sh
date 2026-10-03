#!/usr/bin/env bash

set -euo pipefail

NFT_BIN="/usr/sbin/nft"
CONFIG="/etc/dns-access/nftables.conf"

if [[ ! -x "$NFT_BIN" ]]; then
    echo "[ERROR] nft binary not found."
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "[ERROR] nftables configuration not found."
    exit 1
fi

echo "[INFO] Testing nftables configuration..."

"$NFT_BIN" -c -f "$CONFIG"

echo "[OK] nftables configuration is valid."
