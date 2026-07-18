#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -euo pipefail
command -v citadel >/dev/null 2>&1 || exit 0
citadel down >/dev/null 2>&1 || true
