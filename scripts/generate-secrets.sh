#!/usr/bin/env bash

set -euo pipefail

generate_hex() {
    openssl rand -hex 32
}

generate_base64() {
    openssl rand -base64 32 | tr -d '\n'
}

echo "FLASK_SECRET=$(generate_hex)"
echo "LINK_ENCRYPTION_KEY=$(python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
echo "SESSION_SECRET=$(generate_hex)"
echo "ADMIN_INTERNAL_SECRET=$(generate_base64)"
