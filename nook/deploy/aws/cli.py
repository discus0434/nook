import argparse
import os
import subprocess
import traceback
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values

from nook.deploy.aws.secret_bootstrap import upsert_runtime_secret
from nook.services.runtime import RuntimeSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m nook.deploy.aws.cli")
    parser.add_argument("command", choices=["synth", "diff", "deploy"])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = RuntimeSettings.from_env({})
    try:
        command_env = build_command_env(
            repo_root=settings.repo_root,
            base_env=os.environ,
        )
        if args.command == "deploy":
            command_env["NOOK_AWS_SECRET_ID"] = upsert_runtime_secret(env=command_env)

        subprocess.run(
            ["cdk", args.command],
            cwd=settings.repo_root,
            check=True,
            env=command_env,
        )
    except Exception:
        print(traceback.format_exc())
        raise
    return 0


def build_command_env(
    *,
    repo_root: Path,
    base_env: Mapping[str, str | None],
) -> dict[str, str]:
    dotenv_env = {
        key: value
        for key, value in dotenv_values(repo_root / ".env").items()
        if value is not None
    }
    command_env = dict(dotenv_env)
    command_env.update(
        {key: value for key, value in base_env.items() if value is not None}
    )
    return command_env


if __name__ == "__main__":
    raise SystemExit(main())
