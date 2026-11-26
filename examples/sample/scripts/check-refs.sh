#!/usr/bin/env bash
set -Eeuo pipefail
# The artifact must be a directory containing app.txt.
[[ -d "$1" && -f "$1/app.txt" ]]
