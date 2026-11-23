#!/usr/bin/env bash
# Run the real packaged entry point, first with a defect, then with the fix.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
artifact="$work/deliverable"
mkdir "$artifact"
printf '%s\n' '- [x] Packaged entry point exercised' > "$work/checklist.md"
cat > "$work/refs.sh" <<'SH'
[[ -s "$1/config.txt" && -s "$1/start.sh" ]]
SH
cat > "$work/smoke.sh" <<'SH'
[[ $(bash "$1/start.sh") == ready ]]
SH
printf 'ready\n' > "$artifact/config.txt"
printf '%s\n' 'cat ./config.txt' > "$artifact/start.sh"
gate=(bash "$root/templates/gate.sh" "$artifact" --refs-check "$work/refs.sh"
  --smoke-script "$work/smoke.sh" --checklist "$work/checklist.md")
cd "$work"
printf '%s\n' 'BEFORE | Agent: done. The package has both files.'
if output=$("${gate[@]}" 2>&1); then
  printf '%s\n' "$output" 'Expected the broken package to fail.' >&2
  exit 1
fi
printf '%s\n' "$output" | awk '/FAIL|gate:/{print}'
[[ "$output" == *'FAIL  real smoke script exits 0'* ]]
printf '%s\n' 'AFTER | Resolve config relative to the packaged entry point.'
printf '%s\n' 'cat "$(dirname -- "$0")/config.txt"' > "$artifact/start.sh"
printf '%s\n' '- [x] Verified entry point from outside the package' >> "$work/checklist.md"
"${gate[@]}"
printf '%s\n' 'LESSON | Smoke-run the packaged entry point from a fresh directory.'
