#!/usr/bin/env bash

set -euo pipefail

DOMAIN="${1:-}"
EXPECTED_IP="${2:-}"

if [[ -z "$DOMAIN" || -z "$EXPECTED_IP" ]]; then
    echo "Usage: $0 <domain> <expected-ip>"
    exit 1
fi

resolve_ipv4() {
    if command -v dig >/dev/null 2>&1; then
        dig +short A "$DOMAIN" |
            awk 'NF {print; exit}'
        return
    fi

    getent ahostsv4 "$DOMAIN" |
        awk 'NR==1 {print $1}'
}

RESOLVED_IP="$(resolve_ipv4)"

if [[ -z "$RESOLVED_IP" ]]; then
    echo "[ERROR] Domain does not resolve: $DOMAIN"
    exit 1
fi

echo "Domain : $DOMAIN"
echo "Found  : $RESOLVED_IP"
echo "Expect : $EXPECTED_IP"

if [[ "$RESOLVED_IP" != "$EXPECTED_IP" ]]; then
    echo "[ERROR] DNS record does not match."
    exit 1
fi

echo "[OK] DNS record matches the server IP."
