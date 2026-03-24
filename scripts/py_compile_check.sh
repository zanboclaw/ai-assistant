#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mapfile -t python_files < <(find apps/api apps/worker core tests scripts migrations -type f -name '*.py' | sort)

if [[ "${#python_files[@]}" -eq 0 ]]; then
  echo "No Python files found."
  exit 0
fi

python3 -m py_compile "${python_files[@]}"
echo "Python compile check passed for ${#python_files[@]} files."
