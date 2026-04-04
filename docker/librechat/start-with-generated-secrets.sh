#!/bin/sh

set -eu

generated_any=0

generate_hex() {
  bytes="$1"
  node -e "const bytes = Number(process.argv[1]); process.stdout.write(require('crypto').randomBytes(bytes).toString('hex'));" "$bytes"
}

ensure_hex_secret() {
  var_name="$1"
  bytes="$2"

  eval "current_value=\${$var_name:-}"
  if [ -n "$current_value" ]; then
    return
  fi

  generated_value="$(generate_hex "$bytes")"
  export "$var_name=$generated_value"
  generated_any=1

  >&2 printf '[stihia-librechat] Generated %s for this container start.\n' "$var_name"
}

ensure_hex_secret "CREDS_KEY" "32"
ensure_hex_secret "CREDS_IV" "16"
ensure_hex_secret "JWT_SECRET" "32"
ensure_hex_secret "JWT_REFRESH_SECRET" "32"

if [ "$generated_any" -eq 1 ]; then
  >&2 printf '[stihia-librechat] Using ephemeral auth secrets. Set CREDS_KEY, CREDS_IV, JWT_SECRET, and JWT_REFRESH_SECRET in .env to persist sessions across restarts.\n'
fi

exec docker-entrypoint.sh "$@"
