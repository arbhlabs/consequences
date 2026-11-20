#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
GATE="$ROOT/templates/gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT

fail() { printf 'TEST FAIL: %s\n' "$1" >&2; exit 1; }
pass() { printf 'TEST PASS: %s\n' "$1"; }

bash -n "$GATE" || fail 'gate.sh syntax'
if grep -Eq '(^|[;&|[:space:]])eval([[:space:]]|$)' "$GATE"; then
  fail 'gate.sh must not use eval'
fi
pass 'no eval and valid Bash syntax'

# An apostrophe and shell metacharacters in the artifact path must stay data.
cd "$TMP"
ARTIFACT="$TMP/artifact' ; touch PWNED ; #"
mkdir -p -- "$ARTIFACT"
printf 'hello\n' > "$ARTIFACT/readme.txt"
REFS="$TMP/reference checker.sh"
SMOKE="$TMP/smoke check.sh"
CHECKLIST="$TMP/CHECKLIST.md"
cat > "$REFS" <<'REFS_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ -d "$1" && -f "$1/readme.txt" ]]
REFS_EOF
cat > "$SMOKE" <<'SMOKE_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ -d "$1" && -s "$1/readme.txt" ]]
SMOKE_EOF
cat > "$CHECKLIST" <<'CHECKLIST_EOF'
# Test checklist
- [x] Artifact reviewed
- [x] References checked
CHECKLIST_EOF
printf 'PNG fixture bytes\n' > "$TMP/screenshot.png"

BASE_ARGS=("$ARTIFACT" --refs-check "$REFS" --smoke-script "$SMOKE" --checklist "$CHECKLIST")
OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" 2>&1) || fail "valid gate failed: $OUTPUT"
[[ "$OUTPUT" == *'gate: pass 6/6'* ]] || fail 'valid gate did not report 6/6'
[[ ! -e "$TMP/PWNED" ]] || fail 'shell metacharacters in artifact path executed'
[[ "$OUTPUT" =~ sha256:\ [a-f0-9]{64} ]] || fail 'artifact SHA-256 was not reported'
pass 'spaces, apostrophe and shell metacharacters remain literal'
pass 'artifact SHA-256 evidence is emitted'
pass 'artifact, secret scan, reference helper, smoke helper and checklist pass'

OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" --ui --screenshot "$TMP/screenshot.png" --visual-reviewed 2>&1) || fail "UI gate failed: $OUTPUT"
[[ "$OUTPUT" == *'gate: pass 7/7'* ]] || fail 'UI gate did not report 7/7'
pass 'UI gate requires and verifies screenshot file plus explicit review attestation'

OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" --ui 2>&1) && fail 'UI gate accepted missing screenshot/review acknowledgement'
[[ "$OUTPUT" == *'--ui requires --screenshot'* ]] || fail 'wrong error for missing UI screenshot'
pass 'UI gate rejects missing screenshot/review acknowledgement'

printf 'api_key="%s"\n' 'THIS_IS_A_TEST_SECRET_VALUE' > "$ARTIFACT/secret.txt"
OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" 2>&1) && fail 'secret fixture passed'
[[ "$OUTPUT" == *'FAIL  no obvious secret assignments in artifact'* ]] || fail 'secret scan did not fail clearly'
[[ "$OUTPUT" != *'THIS_IS_A_TEST_SECRET_VALUE'* ]] || fail 'secret scanner leaked matched content'
rm -f -- "$ARTIFACT/secret.txt"
pass 'secret-pattern fixture is rejected without printing the matching value'

printf '%s\n' '- [ ] Not yet verified' >> "$CHECKLIST"
OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" 2>&1) && fail 'unchecked checklist item passed'
[[ "$OUTPUT" == *'FAIL  checklist is complete'* ]] || fail 'unchecked checklist item did not fail'
sed -i '/Not yet verified/d' "$CHECKLIST"
pass 'unchecked checklist item is rejected'

cat > "$REFS" <<'REFS_FAIL_EOF'
#!/usr/bin/env bash
exit 9
REFS_FAIL_EOF
OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" 2>&1) && fail 'failing reference checker passed'
[[ "$OUTPUT" == *'FAIL  references resolve'* ]] || fail 'reference-check failure was not reported'
cat > "$REFS" <<'REFS_RESTORE_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ -d "$1" && -f "$1/readme.txt" ]]
REFS_RESTORE_EOF
pass 'failing reference checker blocks the gate'

cat > "$SMOKE" <<'SMOKE_FAIL_EOF'
#!/usr/bin/env bash
exit 17
SMOKE_FAIL_EOF
OUTPUT=$(bash "$GATE" "${BASE_ARGS[@]}" 2>&1) && fail 'failing smoke test passed'
[[ "$OUTPUT" == *'FAIL  real smoke script exits 0'* ]] || fail 'smoke failure was not reported'
pass 'nonzero smoke test blocks the gate'

# Version consistency is part of release hygiene.
SKILL="$ROOT/skills/ship-gate/SKILL.md"
CHANGELOG="$ROOT/CHANGELOG.md"
if [[ -f "$SKILL" && -f "$CHANGELOG" ]]; then
  SKILL_VERSION=$(sed -n 's/^version: *//p' "$SKILL" | head -n 1)
  CHANGELOG_VERSION=$(sed -n 's/^## *\([0-9][0-9.]*\).*/\1/p' "$CHANGELOG" | head -n 1)
  [[ -n "$SKILL_VERSION" && "$SKILL_VERSION" == "$CHANGELOG_VERSION" ]] || fail "version mismatch: skill=$SKILL_VERSION changelog=$CHANGELOG_VERSION"
  pass "skill and changelog versions match ($SKILL_VERSION)"
fi

for installer in install.sh install.ps1; do
  [[ -f "$ROOT/$installer" ]] || fail "$installer is missing"
  grep -Fq 'templates/gate.sh' "$ROOT/$installer" || fail "$installer does not install gate.sh"
  grep -Fq 'templates/CHECKLIST.md' "$ROOT/$installer" || fail "$installer does not install CHECKLIST.md"
done
grep -Fq 'all checklist boxes to be checked' "$ROOT/templates/CHECKLIST.md" || fail 'checklist template does not explain completion gating'
pass 'both installers deploy the gate runner and checklist'

# Exercise the Bash installer offline with a curl stub; no network is used.
MOCK_BIN="$TMP/mock-bin"
INSTALL_DEST="$TMP/install target"
mkdir -p "$MOCK_BIN"
cat > "$MOCK_BIN/curl" <<'CURL_MOCK_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
out=''
url=''
while (($#)); do
  case "$1" in
    -o) out=$2; shift 2 ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
[[ -n "$out" && -n "$url" ]]
case "$url" in
  */skills/ship-gate/SKILL.md) source_file="$FIXTURE_ROOT/skills/ship-gate/SKILL.md" ;;
  */templates/gate.sh) source_file="$FIXTURE_ROOT/templates/gate.sh" ;;
  */templates/CHECKLIST.md) source_file="$FIXTURE_ROOT/templates/CHECKLIST.md" ;;
  *) printf 'unexpected installer URL: %s\n' "$url" >&2; exit 2 ;;
esac
cp -- "$source_file" "$out"
CURL_MOCK_EOF
chmod +x "$MOCK_BIN/curl"
FIXTURE_ROOT="$ROOT" PATH="$MOCK_BIN:$PATH" bash "$ROOT/install.sh" "$INSTALL_DEST" >/dev/null
cmp -s "$ROOT/skills/ship-gate/SKILL.md" "$INSTALL_DEST/SKILL.md" || fail 'Bash installer copied the wrong skill file'
cmp -s "$ROOT/templates/gate.sh" "$INSTALL_DEST/templates/gate.sh" || fail 'Bash installer copied the wrong gate runner'
cmp -s "$ROOT/templates/CHECKLIST.md" "$INSTALL_DEST/templates/CHECKLIST.md" || fail 'Bash installer copied the wrong checklist'
[[ -x "$INSTALL_DEST/templates/gate.sh" ]] || fail 'Bash installer did not preserve executable permissions'
pass 'Bash installer deploys all three files to a path containing spaces (offline fixture)'

# CI must run both linting and regression tests on pushes and pull requests.
CI_WORKFLOW="$ROOT/.github/workflows/ci.yml"
[[ -f "$CI_WORKFLOW" ]] || fail 'GitHub Actions CI workflow is missing'
grep -Fq 'shellcheck install.sh templates/gate.sh tests/test-gate.sh' "$CI_WORKFLOW" || fail 'CI workflow does not run ShellCheck'
grep -Fq 'bash tests/test-gate.sh' "$CI_WORKFLOW" || fail 'CI workflow does not run regression tests'
pass 'GitHub Actions CI runs ShellCheck and the regression suite'

# Scan this repository copy as a directory artifact to guard against test-fixture false positives.
REPO_REFS="$TMP/repo-reference-check.sh"
REPO_SMOKE="$TMP/repo-smoke-test.sh"
REPO_CHECKLIST="$TMP/repo-CHECKLIST.md"
cat > "$REPO_REFS" <<'REPO_REFS_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
[[ -f "$1/README.md" && -f "$1/templates/gate.sh" && -f "$1/install.ps1" ]]
REPO_REFS_EOF
cat > "$REPO_SMOKE" <<'REPO_SMOKE_EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
bash -n "$1/templates/gate.sh"
REPO_SMOKE_EOF
cat > "$REPO_CHECKLIST" <<'REPO_CHECKLIST_EOF'
# Repo validation
- [x] Runner syntax checked
- [x] Installer assets present
REPO_CHECKLIST_EOF
OUTPUT=$(bash "$GATE" "$ROOT" --refs-check "$REPO_REFS" --smoke-script "$REPO_SMOKE" --checklist "$REPO_CHECKLIST" 2>&1) || fail "repository directory artifact failed its own gate: $OUTPUT"
[[ "$OUTPUT" == *'gate: pass 6/6'* ]] || fail 'repository directory gate did not report 6/6'
pass 'repository directory scan has no secret-fixture false positives and emits a manifest hash'

printf '\nAll Consequences gate tests passed.\n'