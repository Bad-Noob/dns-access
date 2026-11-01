#!/usr/bin/env bash

set -euo pipefail

SERVICES=(
    "nftables.service"
    "unbound.service"
    "AdGuardHome.service"
    "dns-access.service"
    "dns-admin.service"
)

FAILED=0

echo "========================================"
echo " DNS Access Service Check"
echo "========================================"
echo

for service in "${SERVICES[@]}"; do

    if systemctl is-enabled --quiet "$service" 2>/dev/null; then
        ENABLED="enabled"
    else
        ENABLED="disabled"
    fi

    if systemctl is-active --quiet "$service" 2>/dev/null; then
        ACTIVE="active"
    else
        ACTIVE="inactive"
        FAILED=$((FAILED + 1))
    fi

    printf '%-28s %-10s %s\n' \
        "$service" \
        "$ACTIVE" \
        "$ENABLED"

done

echo

if [[ "$FAILED" -gt 0 ]]; then
    echo "[ERROR] $FAILED service(s) are not active."
    exit 1
fi

echo "[OK] All required services are active."
