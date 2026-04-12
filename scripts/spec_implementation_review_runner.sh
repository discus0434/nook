#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/spec_review_common.sh
source "$SCRIPT_DIR/spec_review_common.sh"

build_prompt() {
  local spec_path="$1"
  cat <<EOF
You are a read-only spec-implementation-review agent. Do not modify files.

Target spec:
- $spec_path

Review procedure:
1. Read the target spec carefully.
2. Extract the promised behaviors, touched files, tests, docs updates, and verification steps.
3. Compare those expectations with the current repository and verify whether the implementation would work as intended.
4. Focus on implementation quality, runtime behavior, and test adequacy. Do not flag docs updates or spec deletion tasks as gaps.
5. Output OK / GAP / FIX with severity (Critical/Major/Minor/Info), citing concrete spec sections and file paths when possible.
6. Do NOT run make spec-implementation-review or invoke spec_implementation_review_runner.sh recursively.
Then exit.
EOF
}

main() {
  local output_path="${OUTPUT:-/tmp/spec-implementation-review.txt}"
  local spec_path

  validate_codex_cli
  spec_path="$(resolve_active_spec "$REPO_ROOT")"

  echo "[spec-implementation-review] target: $spec_path" >&2
  echo "[spec-implementation-review] output: $output_path" >&2

  run_codex_review "$REPO_ROOT" "$output_path" "$(build_prompt "$spec_path")"
}

main "$@"
