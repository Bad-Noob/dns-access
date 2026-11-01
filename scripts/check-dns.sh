#!/usr/bin/env bash

set -euo pipefail

DNS_SERVER="${1:-127.0.0.1}"
QUERY_NAME="${2:-example.com}"

if ! command -v dig >/dev/null 2>&1; then
    echo "[ERROR] dig is required. Install dnsutils."
    exit 1
fi

echo "DNS server : $DNS_SERVER"
echo "Query name : $QUERY_NAME"

if ! dig @"$DNS_SERVER" "$QUERY_NAME" A +time=3 +tries=1 +noall +answer; then
    echo "[ERROR] DNS query failed."
    exit 1
fi

echo "[OK] DNS query completed."
