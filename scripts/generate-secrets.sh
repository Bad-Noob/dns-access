#!/usr/bin/env bash

set -euo pipefail

generate_hex() {
    openssl rand -hex 32
}

generate_base64() {
    openssl rand -base64 48 | tr -d '\n'
}

generate_fernet_key() {
    python3 - <<'PY'
import base64
import os

print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
}

echo "FLASK_SECRET=$(generate_hex)"
echo "LINK_ENCRYPTION_KEY=$(generate_fernet_key)"
echo "SESSION_SECRET=$(generate_hex)"
echo "ADMIN_INTERNAL_SECRET=$(generate_base64)"
