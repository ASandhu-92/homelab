#!/usr/bin/env bash
# Validate every compose file in the repo with `docker compose config`,
# using the folder's .env.example so every ${VAR} has a value.
# Exits non-zero if any file fails. Needs Docker with the compose plugin.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

fail=0
count=0
while IFS= read -r file; do
  dir=$(dirname "$file")
  args=(-f "$(basename "$file")")
  [[ -f "$dir/.env.example" ]] && args=(--env-file .env.example "${args[@]}")
  if out=$(cd "$dir" && docker compose "${args[@]}" config -q 2>&1); then
    echo "ok    $file"
  else
    echo "FAIL  $file"
    printf '%s\n' "$out" | sed 's/^/      /'
    fail=1
  fi
  count=$((count + 1))
done < <(find . -path ./.git -prune -o \( -name compose.yaml -o -name docker-compose.yml \) -print | sort)

echo "$count compose files checked"
if [[ "$count" -eq 0 ]]; then
  echo "no compose files found" >&2
  exit 1
fi
exit "$fail"
