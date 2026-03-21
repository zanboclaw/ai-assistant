#!/usr/bin/env bash
set -euo pipefail

sandbox_file="${STAGE7_SANDBOX_FILE:-}"
expected_contains="${STAGE7_EXPECT_CONTAINS:-}"
expected_absent="${STAGE7_EXPECT_ABSENT:-}"

if [[ -z "$sandbox_file" ]]; then
  echo "STAGE7_SANDBOX_FILE is required" >&2
  exit 2
fi

if [[ ! -f "$sandbox_file" ]]; then
  echo "sandbox file not found: $sandbox_file" >&2
  exit 3
fi

if [[ -n "$expected_contains" ]] && ! grep -Fq "$expected_contains" "$sandbox_file"; then
  echo "expected content not found: $expected_contains" >&2
  exit 4
fi

if [[ -n "$expected_absent" ]] && grep -Fq "$expected_absent" "$sandbox_file"; then
  echo "unexpected content found: $expected_absent" >&2
  exit 5
fi

echo "acceptance passed for $sandbox_file"
