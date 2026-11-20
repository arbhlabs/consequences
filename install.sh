#!/usr/bin/env bash
# Install or update the latest ship-gate skill and its runnable templates.
# Usage: curl -fsSL https://raw.githubusercontent.com/arbhlabs/consequences/main/install.sh | bash
set -Eeuo pipefail

BASE_URL='https://raw.githubusercontent.com/arbhlabs/consequences/main'
DEST="${1:-$HOME/.claude/skills/ship-gate}"
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

curl -fsSL "$BASE_URL/skills/ship-gate/SKILL.md" -o "$TMP/SKILL.md"
curl -fsSL "$BASE_URL/templates/gate.sh" -o "$TMP/gate.sh"
curl -fsSL "$BASE_URL/templates/CHECKLIST.md" -o "$TMP/CHECKLIST.md"

mkdir -p -- "$DEST/templates"
install -m 0644 "$TMP/SKILL.md" "$DEST/SKILL.md"
install -m 0755 "$TMP/gate.sh" "$DEST/templates/gate.sh"
install -m 0644 "$TMP/CHECKLIST.md" "$DEST/templates/CHECKLIST.md"

printf 'ship-gate installed/updated at %s\n' "$DEST"
printf 'runner: %s/templates/gate.sh\n' "$DEST"
printf 'checklist: %s/templates/CHECKLIST.md\n' "$DEST"