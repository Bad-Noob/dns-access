#!/usr/bin/env bash

set -euo pipefail

DOMAIN="${1:-}"
EXPECTED_IPV4="${2:-}"
EXPECTED_IPV6="${3:-}"

if [[ -z "$DOMAIN" || -z "$EXPECTED_IPV4" ]]; then
    echo "Usage: $0 <domain> <expected-ipv4> [expected-ipv6]"
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

resolve_ipv6() {
    if command -v dig >/dev/null 2>&1; then
        dig +short AAAA "$DOMAIN" |
            awk 'NF {print; exit}'
        return
    fi

    getent ahostsv6 "$DOMAIN" |
        awk 'NR==1 {print $1}'
}

RESOLVED_IPV4="$(resolve_ipv4)"

if [[ -z "$RESOLVED_IPV4" ]]; then
    echo "[ERROR] Domain does not resolve to an IPv4 address: $DOMAIN"
    exit 1
fi

echo "Domain       : $DOMAIN"
echo "Found IPv4   : $RESOLVED_IPV4"
echo "Expected IPv4: $EXPECTED_IPV4"

if [[ "$RESOLVED_IPV4" != "$EXPECTED_IPV4" ]]; then
    echo "[ERROR] IPv4 DNS record does not match."
    exit 1
fi

if [[ -n "$EXPECTED_IPV6" ]]; then
    RESOLVED_IPV6="$(resolve_ipv6)"

    if [[ -z "$RESOLVED_IPV6" ]]; then
        echo "[ERROR] Domain does not resolve to an IPv6 address."
        exit 1
    fi

    echo "Found IPv6   : $RESOLVED_IPV6"
    echo "Expected IPv6: $EXPECTED_IPV6"

    if [[ "$RESOLVED_IPV6" != "$EXPECTED_IPV6" ]]; then
        echo "[ERROR] IPv6 DNS record does not match."
        exit 1
    fi
fi

echo "[OK] DNS records match the server configuration."
