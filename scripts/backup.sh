#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUPS_DIR="${ROOT}/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
TARGET_DIR="${BACKUPS_DIR}/backup_${TIMESTAMP}"

mkdir -p "${TARGET_DIR}"

echo "Backing up workspace, artifacts, and docs/scripts to ${TARGET_DIR}"

copy_if_exists() {
  local src="$1"
  local dest="$2"

  if [[ -e "${src}" ]]; then
    mkdir -p "$(dirname "${dest}")"
    rsync -a --delete "${src}" "${dest}"
  fi
}

copy_if_exists "${ROOT}/data/workspace/" "${TARGET_DIR}/workspace/"
copy_if_exists "${ROOT}/data/artifacts/" "${TARGET_DIR}/artifacts/"
copy_if_exists "${ROOT}/docs/" "${TARGET_DIR}/docs/"
copy_if_exists "${ROOT}/scripts/" "${TARGET_DIR}/scripts/"

echo "Backup completed: ${TARGET_DIR}"
