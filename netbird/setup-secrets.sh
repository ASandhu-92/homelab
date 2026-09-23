#!/usr/bin/env bash
# Create config.yaml from config.yaml.example with fresh random secrets.
# Refuses to overwrite an existing config.yaml (the encryption key must stay
# stable once the store has data).
set -euo pipefail
cd "$(dirname "$0")"

if [[ -e config.yaml ]]; then
  echo "config.yaml already exists; not overwriting" >&2
  exit 1
fi

relay=$(openssl rand -base64 32 | tr -d '\n')
enc=$(openssl rand -base64 32 | tr -d '\n')

umask 077
sed -e "s|__RELAY_SECRET__|${relay}|" -e "s|__ENC_KEY__|${enc}|" config.yaml.example > config.yaml

if grep -v '^[[:space:]]*#' config.yaml | grep -q -E '__(RELAY_SECRET|ENC_KEY)__'; then
  echo "placeholders left in config.yaml" >&2
  exit 1
fi
echo "wrote config.yaml (mode 600); edit exposedAddress, issuer and redirect URIs next"
