#!/usr/bin/env bash
# Consequences release gate. Project-specific checks are supplied as scripts,
# never as shell fragments. This deliberately does not use eval.
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage:
  gate.sh <artifact> --refs-check <script> --smoke-script <script> --checklist <file> [--ui --screenshot <file> --visual-reviewed]

Required project-specific helpers:
  --refs-check    Bash script that validates the artifact's referenced paths,
                  files, URLs, commands and required environment variables.
                  It receives the artifact path as its first argument.
  --smoke-script  Bash script that launches/tests the actual deliverable and
                  exits 0 only when the real smoke test succeeds. It receives
                  the artifact path as its first argument.
  --checklist     Markdown checklist. Every checkbox must be checked.

For screen-based deliverables, also pass --ui, --screenshot and
--visual-reviewed after opening the screenshot and inspecting it yourself.
The script can verify that the screenshot exists; it cannot judge its pixels.

All helper scripts are invoked as quoted file paths with the artifact as one
argument. No command strings are evaluated.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

[[ $# -ge 1 ]] || { usage >&2; exit 2; }
ARTIFACT=$1
shift
REFS_CHECK=''
SMOKE_SCRIPT=''
CHECKLIST=''
SCREENSHOT=''
IS_UI=0
VISUAL_REVIEWED=0

while (($#)); do
  case "$1" in
    --refs-check)
      (($# >= 2)) || die '--refs-check requires a script path'
      REFS_CHECK=$2; shift 2 ;;
    --smoke-script)
      (($# >= 2)) || die '--smoke-script requires a script path'
      SMOKE_SCRIPT=$2; shift 2 ;;
    --checklist)
      (($# >= 2)) || die '--checklist requires a file path'
      CHECKLIST=$2; shift 2 ;;
    --screenshot)
      (($# >= 2)) || die '--screenshot requires a file path'
      SCREENSHOT=$2; shift 2 ;;
    --ui) IS_UI=1; shift ;;
    --visual-reviewed) VISUAL_REVIEWED=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[[ -n "$REFS_CHECK" && -f "$REFS_CHECK" ]] || die 'provide an existing --refs-check script'
[[ -n "$SMOKE_SCRIPT" && -f "$SMOKE_SCRIPT" ]] || die 'provide an existing --smoke-script'
[[ -n "$CHECKLIST" && -f "$CHECKLIST" ]] || die 'provide an existing --checklist file'
if (( IS_UI )); then
  [[ -n "$SCREENSHOT" ]] || die '--ui requires --screenshot'
  (( VISUAL_REVIEWED )) || die '--ui requires --visual-reviewed after the screenshot has been opened and inspected'
else
  [[ -z "$SCREENSHOT" && $VISUAL_REVIEWED -eq 0 ]] || die '--screenshot and --visual-reviewed require --ui'
fi

PASS=0
TOTAL=0
record_result() {
  local label=$1
  local status=$2
  TOTAL=$((TOTAL + 1))
  if [[ "$status" -eq 0 ]]; then
    PASS=$((PASS + 1))
    printf 'PASS  %s\n' "$label"
  else
    printf 'FAIL  %s\n' "$label"
  fi
}

artifact_exists() { [[ -f "$ARTIFACT" || -d "$ARTIFACT" ]]; }

no_secret_patterns() {
  local pattern="(api[_-]?key|secret|password|pin)[[:space:]]*[:=][[:space:]]*[\"'][^\"']{4,}"
  local status=0
  if [[ -d "$ARTIFACT" ]]; then
    grep -rIEn --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
      --exclude-dir=.gradle --exclude-dir=build --exclude-dir=dist \
      -e "$pattern" -- "$ARTIFACT" >/dev/null 2>&1 || status=$?
  else
    grep -IEn -e "$pattern" -- "$ARTIFACT" >/dev/null 2>&1 || status=$?
  fi
  case "$status" in
    0) printf '  possible secret assignment found (matched content suppressed)\n' >&2; return 1 ;;
    1) return 0 ;;
    *) printf '  secret scanner failed with grep exit %s\n' "$status" >&2; return 1 ;;
  esac
}

references_resolve() { bash -- "$REFS_CHECK" "$ARTIFACT"; }
smoke_run_succeeds() { bash -- "$SMOKE_SCRIPT" "$ARTIFACT"; }

checklist_complete() {
  if ! grep -Eq '^[[:space:]]*-[[:space:]]+\[[xX]\][[:space:]]+' "$CHECKLIST"; then
    printf '  checklist has no completed checkbox items\n' >&2
    return 1
  fi
  if grep -Eq '^[[:space:]]*-[[:space:]]+\[[[:space:]]\][[:space:]]+' "$CHECKLIST"; then
    printf '  checklist still contains unchecked items\n' >&2
    return 1
  fi
}

screenshot_exists_and_reviewed() { [[ -s "$SCREENSHOT" && $VISUAL_REVIEWED -eq 1 ]]; }

sha256_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum | awk 'NR == 1 { print $1 }'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 | awk 'NR == 1 { print $1 }'
  elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 | awk '{ print $NF }'
  else return 1
  fi
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum -- "$1" | awk 'NR == 1 { print $1 }'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 -- "$1" | awk 'NR == 1 { print $1 }'
  elif command -v openssl >/dev/null 2>&1; then openssl dgst -sha256 "$1" | awk '{ print $NF }'
  else return 1
  fi
}

artifact_digest() {
  if [[ -f "$ARTIFACT" ]]; then
    sha256_file "$ARTIFACT"
  elif [[ -d "$ARTIFACT" ]]; then
    (
      while IFS= read -r -d '' file; do
        relative_path=${file#"$ARTIFACT"/}
        file_digest=$(sha256_file "$file") || exit 1
        printf '%s\0%s\0' "$relative_path" "$file_digest"
      done < <(find "$ARTIFACT" -type f -not -path '*/.git/*' -print0 | LC_ALL=C sort -z)
    ) | sha256_stdin
  else
    return 1
  fi
}

if artifact_exists; then record_result 'artifact exists' 0; else record_result 'artifact exists' 1; fi
if no_secret_patterns; then record_result 'no obvious secret assignments in artifact' 0; else record_result 'no obvious secret assignments in artifact' 1; fi
if references_resolve; then record_result 'references resolve' 0; else record_result 'references resolve' 1; fi
if smoke_run_succeeds; then record_result 'real smoke script exits 0' 0; else record_result 'real smoke script exits 0' 1; fi
if checklist_complete; then record_result 'checklist is complete' 0; else record_result 'checklist is complete' 1; fi
if (( IS_UI )); then
  if screenshot_exists_and_reviewed; then record_result 'screenshot exists and visual review was attested' 0; else record_result 'screenshot exists and visual review was attested' 1; fi
  printf 'VISUAL REVIEW: this script cannot inspect pixels; the agent must open and inspect %s\n' "$SCREENSHOT"
fi

DIGEST=''
if DIGEST=$(artifact_digest 2>/dev/null) && [[ "$DIGEST" =~ ^[a-f0-9]{64}$ ]]; then
  record_result 'artifact SHA-256 evidence available' 0
else
  DIGEST='unavailable'
  record_result 'artifact SHA-256 evidence available' 1
fi
printf 'artifact: %s\n' "$ARTIFACT"
printf 'sha256: %s\n' "$DIGEST"
printf 'gate: pass %s/%s\n' "$PASS" "$TOTAL"
if (( PASS != TOTAL )); then exit 1; fi