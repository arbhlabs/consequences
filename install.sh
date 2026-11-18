#!/usr/bin/env bash
# Install or update the latest ship-gate skill. Usage: curl -fsSL https://raw.githubusercontent.com/arbhlabs/ship-gate/main/install.sh | bash
set -euo pipefail
URL="https://raw.githubusercontent.com/arbhlabs/ship-gate/main/skills/ship-gate/SKILL.md"
DEST="${1:-$HOME/.claude/skills/ship-gate}"
mkdir -p "$DEST"
curl -fsSL "$URL" -o "$DEST/SKILL.md"
echo "ship-gate installed/updated at $DEST/SKILL.md"
