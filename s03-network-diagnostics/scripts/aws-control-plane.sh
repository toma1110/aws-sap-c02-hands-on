#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SOURCE="${SCRIPT_DIR}/aws_control_plane.py"

if [[ ! -f "${PYTHON_SOURCE}" ]]; then
  printf '{"error":"underlying Python source is missing: scripts/aws_control_plane.py"}\n' >&2
  exit 2
fi

exec python3 "${PYTHON_SOURCE}" "$@"
