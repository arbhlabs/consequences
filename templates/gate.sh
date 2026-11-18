#!/usr/bin/env bash
# Minimal ship-gate runner. Edit the checks for your deliverable; keep it cheap.
set -u
ARTIFACT="${1:?usage: gate.sh <artifact>}"
pass=0; total=0
check(){ total=$((total+1)); if eval "$2" >/dev/null 2>&1; then pass=$((pass+1)); echo "PASS  $1"; else echo "FAIL  $1"; fi; }

check "artifact exists"            "test -e '$ARTIFACT'"
check "no secrets in artifact"     "! grep -rIiE '(api[_-]?key|secret|password|pin)\s*[:=]\s*[\"'\''][^\"'\'']{4,}' '$ARTIFACT'"
# check "every reference resolves"  "./check-refs.sh '$ARTIFACT'"
# check "smoke run exits 0"         "./smoke.sh '$ARTIFACT'"

echo "sha256: $(sha256sum "$ARTIFACT" 2>/dev/null | cut -c1-16 || echo n/a)"
echo "gate: pass $pass/$total"
[ "$pass" -eq "$total" ]
