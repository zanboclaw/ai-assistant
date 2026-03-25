#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PLAYWRIGHT_CACHE_DIR="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"

echo "[playwright] checking Node and package scripts"
node --version
npx playwright --version

shopt -s nullglob
bins=("${PLAYWRIGHT_CACHE_DIR}"/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell)
shopt -u nullglob

if [[ ${#bins[@]} -eq 0 ]]; then
  echo "[playwright] chromium headless shell is not installed yet"
  echo "[playwright] run: npx playwright install chromium"
  exit 1
fi

bin="${bins[-1]}"
echo "[playwright] inspecting browser binary: $bin"

if ! command -v ldd >/dev/null 2>&1; then
  echo "[playwright] ldd is unavailable; skip shared library diagnostics"
  exit 0
fi

missing_libs="$(ldd "$bin" | grep 'not found' || true)"
if [[ -n "$missing_libs" ]]; then
  echo "[playwright] missing shared libraries detected:"
  echo "$missing_libs"
  echo "[playwright] try: npx playwright install --with-deps chromium"
  exit 1
fi

echo "[playwright] shared library check passed"
