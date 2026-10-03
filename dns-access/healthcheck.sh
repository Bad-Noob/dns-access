#!/usr/bin/env bash

set -u

OK=0
FAIL=0

check() {
    local name="$1"
    shift

    if "$@" >/dev/null 2>&1; then
        printf '[OK]   %s\n' "$name"
        OK=$((OK + 1))
    else
        printf '[FAIL] %s\n' "$name"
        FAIL=$((FAIL + 1))
    fi
}

echo
echo "========================================"
echo " DNS Access Health Check"
echo "========================================"
echo

check "dns-access service" systemctl is-active --quiet dns-access.service
check "dns-admin service" systemctl is-active --quiet dns-admin.service
check "unbound service" systemctl is-active --quiet unbound.service
check "AdGuard Home service" systemctl is-active --quiet AdGuardHome.service
check "nginx service" systemctl is-active --quiet nginx.service
check "nftables service" systemctl is-active --quiet nftables.service

check "DNS IPv4 port 53" bash -c 'ss -lunpt 2>/dev/null | grep -Eq "0\.0\.0\.0:53[[:space:]]|127\.0\.0\.1:53[[:space:]]"'

check "DNS over HTTPS port 443" bash -c 'ss -lntp 2>/dev/null | grep -Eq "0\.0\.0\.0:443[[:space:]]|\[::\]:443[[:space:]]"'

check "Unbound port 5353" bash -c 'ss -lunpt 2>/dev/null | grep -Eq "127\.0\.0\.1:5353[[:space:]]"'

check "DNS Access port 8787" bash -c 'ss -lntp 2>/dev/null | grep -Eq "127\.0\.0\.1:8787[[:space:]]"'

check "Admin port 8790" bash -c 'ss -lntp 2>/dev/null | grep -Eq "127\.0\.0\.1:8790[[:space:]]"'

if [[ -f /etc/dns-access/nftables.conf ]]; then
    check "nftables configuration" /usr/sbin/nft -c -f /etc/dns-access/nftables.conf
fi

if [[ -f /etc/nginx/nginx.conf ]]; then
    check "nginx configuration" /usr/sbin/nginx -t
fi

if [[ -f /etc/unbound/unbound.conf ]]; then
    check "Unbound configuration" /usr/sbin/unbound-checkconf /etc/unbound/unbound.conf
fi

echo
echo "========================================"
echo " Passed: $OK"
echo " Failed: $FAIL"
echo "========================================"
echo

if [[ "$FAIL" -gt 0 ]]; then
    exit 1
fi

exit 0
