#!/bin/bash
set -euo pipefail

resolve_repo_root() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[1]}")" && pwd)"
  cd "$script_dir/.." && pwd
}

validate_codex_cli() {
  if command -v codex >/dev/null 2>&1; then
    return 0
  fi

  echo "[spec-review] ERROR: codex CLI not found. Ensure Codex CLI is installed and available on PATH." >&2
  return 2
}

resolve_active_spec() {
  local repo_root="$1"
  local spec_dir="$repo_root/specs"
  local -a specs=()
  local path

  if [ ! -d "$spec_dir" ]; then
    echo "[spec-review] ERROR: specs directory not found: $spec_dir" >&2
    return 2
  fi

  while IFS= read -r path; do
    if [ -z "$path" ]; then
      continue
    fi
    if [ "$(basename "$path")" = "TEMPLATE.md" ]; then
      continue
    fi
    specs+=("${path#$repo_root/}")
  done < <(find "$spec_dir" -maxdepth 1 -type f -name "*.md" | LC_ALL=C sort)

  if [ "${#specs[@]}" -ne 1 ]; then
    echo "[spec-review] ERROR: Expected exactly one active spec, found ${#specs[@]}." >&2
    if [ "${#specs[@]}" -gt 0 ]; then
      printf '  - %s\n' "${specs[@]}" >&2
    fi
    return 2
  fi

  printf '%s\n' "${specs[0]}"
}

run_codex_review() {
  local repo_root="$1"
  local output_path="$2"
  local prompt="$3"
  local codex_model="${CODEX_MODEL:-gpt-5-codex}"

  (
    cd "$repo_root"
    codex exec \
      -s read-only \
      -m "$codex_model" \
      -c model_reasoning_effort="medium" \
      -C . \
      --output-last-message "$output_path" \
      "$prompt"
  )
}
