#!/usr/bin/env bash
set -Eeuo pipefail
# Require a VERSION file in the artifact, then check its contents.
[[ -d "$1" && -f "$1/VERSION" ]] || { printf 'smoke: VERSION file missing in %s\n' "$1" >&2; exit 1; }
grep -Eq '^1\.' "$1/VERSION"
