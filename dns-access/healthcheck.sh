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

check "dns-access service" \
    systemctl is-active --quiet dns-access.service

check "dns-admin service" \
    systemctl is-active --quiet dns-admin.service

check "unbound service" \
    systemctl is-active --quiet unbound.service

check "AdGuard Home service" \
    systemctl is-active --quiet AdGuardHome.service

check "nginx service" \
    systemctl is-active --quiet nginx.service

check "nftables service" \
    systemctl is-active --quiet nftables.service

check "DNS port 53" \
    ss -lunpt \
        | grep -Eq '(:53[[:space:]]|:53$)'

check "DNS over HTTPS port 443" \
    ss -lntp \
        | grep -Eq '(:443[[:space:]]|:443$)'

check "Unbound port 5353" \
    ss -lunpt \
        | grep -Eq '127\.0\.0\.1:5353'

check "DNS Access port 8787" \
    ss -lntp \
        | grep -Eq '127\.0\.0\.1:8787'

check "Admin port 8790" \
    ss -lntp \
        | grep -Eq '127\.0\.0\.1:8790'

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
