import os
import shutil
import subprocess
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _install_runner_fixture(tmp_path: Path, runner_names: list[str]) -> Path:
    repo_root = _repo_root()
    fixture_root = tmp_path / "repo"
    (fixture_root / "specs").mkdir(parents=True)
    (fixture_root / "scripts").mkdir(parents=True)
    (fixture_root / "specs" / "TEMPLATE.md").write_text(
        "# template\n", encoding="utf-8"
    )

    for runner_name in runner_names:
        source = repo_root / "scripts" / runner_name
        target = fixture_root / "scripts" / runner_name
        shutil.copy2(source, target)
        target.chmod(0o755)

    common = repo_root / "scripts" / "spec_review_common.sh"
    common_target = fixture_root / "scripts" / "spec_review_common.sh"
    shutil.copy2(common, common_target)
    common_target.chmod(0o755)

    return fixture_root


def _install_fake_codex(tmp_path: Path) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex = fake_bin / "codex"
    codex.write_text(
        """#!/bin/bash
set -euo pipefail
printf '%s\\0' "$@" > "$FAKE_CODEX_ARGS"
output=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output-last-message" ]; then
    shift
    output="$1"
  fi
  shift
done
if [ -n "$output" ]; then
  printf 'fake review\\n' > "$output"
fi
""",
        encoding="utf-8",
    )
    codex.chmod(0o755)
    return fake_bin


def _run_runner(
    fixture_root: Path,
    runner_name: str,
    *,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides or {})
    return subprocess.run(
        [str(fixture_root / "scripts" / runner_name)],
        cwd=fixture_root,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_spec_review_runner_invokes_codex_with_baked_prompt(
    tmp_path: Path,
) -> None:
    fixture_root = _install_runner_fixture(tmp_path, ["spec_review_runner.sh"])
    fake_bin = _install_fake_codex(tmp_path)
    (fixture_root / "specs" / "feature.md").write_text("# spec\n", encoding="utf-8")
    args_path = tmp_path / "codex-args.bin"
    output_path = tmp_path / "spec-review.txt"

    result = _run_runner(
        fixture_root,
        "spec_review_runner.sh",
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_CODEX_ARGS": str(args_path),
            "OUTPUT": str(output_path),
            "CODEX_MODEL": "test-model",
        },
    )

    assert result.returncode == 0
    assert output_path.read_text(encoding="utf-8") == "fake review\n"

    args = args_path.read_bytes().split(b"\0")
    prompt = args[-2].decode("utf-8")
    decoded = [arg.decode("utf-8") for arg in args[:-1]]
    assert decoded[:3] == ["exec", "-s", "read-only"]
    assert "--output-last-message" in decoded
    assert "test-model" in decoded
    assert "You are a read-only spec-review agent." in prompt
    assert "Target spec:" in prompt
    assert "- specs/feature.md" in prompt
    assert "Output OK / GAP / FIX" in prompt


def test_spec_implementation_review_runner_invokes_codex_with_baked_prompt(
    tmp_path: Path,
) -> None:
    fixture_root = _install_runner_fixture(
        tmp_path, ["spec_implementation_review_runner.sh"]
    )
    fake_bin = _install_fake_codex(tmp_path)
    (fixture_root / "specs" / "feature.md").write_text("# spec\n", encoding="utf-8")
    args_path = tmp_path / "codex-args.bin"
    output_path = tmp_path / "spec-implementation-review.txt"

    result = _run_runner(
        fixture_root,
        "spec_implementation_review_runner.sh",
        env_overrides={
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_CODEX_ARGS": str(args_path),
            "OUTPUT": str(output_path),
        },
    )

    assert result.returncode == 0
    assert output_path.read_text(encoding="utf-8") == "fake review\n"

    args = args_path.read_bytes().split(b"\0")
    prompt = args[-2].decode("utf-8")
    assert "You are a read-only spec-implementation-review agent." in prompt
    assert "- specs/feature.md" in prompt
    assert "Do not flag docs updates or spec deletion tasks as gaps." in prompt


def test_spec_review_runner_fails_without_active_spec(tmp_path: Path) -> None:
    fixture_root = _install_runner_fixture(
        tmp_path,
        ["spec_review_runner.sh"],
    )
    fake_bin = _install_fake_codex(tmp_path)

    result = _run_runner(
        fixture_root,
        "spec_review_runner.sh",
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "Expected exactly one active spec" in result.stderr


def test_spec_review_runner_fails_with_multiple_active_specs(tmp_path: Path) -> None:
    fixture_root = _install_runner_fixture(
        tmp_path,
        ["spec_review_runner.sh"],
    )
    fake_bin = _install_fake_codex(tmp_path)
    (fixture_root / "specs" / "one.md").write_text("# one\n", encoding="utf-8")
    (fixture_root / "specs" / "two.md").write_text("# two\n", encoding="utf-8")

    result = _run_runner(
        fixture_root,
        "spec_review_runner.sh",
        env_overrides={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "Expected exactly one active spec" in result.stderr


def test_spec_review_runner_fails_when_codex_is_unavailable(tmp_path: Path) -> None:
    fixture_root = _install_runner_fixture(
        tmp_path,
        ["spec_review_runner.sh"],
    )
    (fixture_root / "specs" / "feature.md").write_text("# spec\n", encoding="utf-8")

    result = _run_runner(
        fixture_root,
        "spec_review_runner.sh",
        env_overrides={"PATH": "/usr/bin:/bin"},
    )

    assert result.returncode != 0
    assert "codex CLI not found" in result.stderr
