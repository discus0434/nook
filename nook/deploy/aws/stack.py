import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import jsii
from aws_cdk import (
    AssetHashType,
    BundlingOptions,
    Duration,
    ILocalBundling,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk.aws_lambda import Code, Function, Runtime
from constructs import Construct

from nook.deploy.aws.runtime_config import (
    COMMON_REQUIREMENTS,
    EXTRA_INSTALL_COMMANDS,
    MEMORY_SIZES,
    PROJECT_ROOT,
    RUNTIME_SOURCE_DIRECTORIES,
    TIMEOUT_SECONDS,
    AwsStackConfig,
    build_runtime_environment,
    requirements_path_for,
)
from nook.services.catalog import SERVICE_DEFINITIONS


@dataclass
class NookNames:
    hacker_news: str = "hacker_news"
    paper_summarizer: str = "paper_summarizer"
    reddit_explorer: str = "reddit_explorer"
    tech_feed: str = "tech_feed"
    github_trending: str = "github_trending"
    product_hunt: str = "product_hunt"
    viewer: str = "viewer"
    google_alerts: str = "google_alerts"
    tech_news: str = "tech_news"


class NookStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: AwsStackConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        s3_bucket = s3.Bucket(
            self,
            id="NookBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        runtime_secret = _import_runtime_secret(self, config.runtime_secret_id)
        viewer_environment = build_runtime_environment(
            bucket_name=s3_bucket.bucket_name,
            runtime_secret_id=config.runtime_secret_id,
            llm_model=config.llm_model,
        )
        viewer_invoke_policy = iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[],
        )

        for definition in SERVICE_DEFINITIONS:
            if definition.kind != "collector":
                continue

            lambda_function = Function(
                self,
                id=definition.name,
                runtime=Runtime.PYTHON_3_11,
                code=_build_lambda_code(definition.name),
                handler=f"nook.deploy.aws.handlers.{definition.name}.lambda_handler",
                environment=build_runtime_environment(
                    bucket_name=s3_bucket.bucket_name,
                    runtime_secret_id=config.runtime_secret_id,
                    llm_model=config.llm_model,
                ),
                memory_size=MEMORY_SIZES.get(definition.name, 128),
                timeout=Duration.seconds(TIMEOUT_SECONDS.get(definition.name, 900)),
            )

            s3_bucket.grant_read_write(lambda_function)
            runtime_secret.grant_read(lambda_function)
            viewer_invoke_policy.add_resources(lambda_function.function_arn)
            viewer_environment[f"{definition.name.upper()}_FUNCTION_ARN"] = (
                lambda_function.function_arn
            )

            if definition.schedule is None:
                continue
            hour, minute = definition.schedule
            rule = events.Rule(
                self,
                id=f"DailyRule{definition.name}",
                schedule=events.Schedule.cron(
                    minute=str(minute),
                    hour=str(hour),
                    month="*",
                    week_day="*",
                    year="*",
                ),
            )
            rule.add_target(targets.LambdaFunction(lambda_function))

        viewer_function = Function(
            self,
            id="viewer",
            runtime=Runtime.PYTHON_3_11,
            code=_build_lambda_code("viewer"),
            handler="nook.deploy.aws.handlers.viewer.lambda_handler",
            environment=viewer_environment,
            memory_size=MEMORY_SIZES.get("viewer", 128),
            timeout=Duration.seconds(TIMEOUT_SECONDS["viewer"]),
        )
        s3_bucket.grant_read_write(viewer_function)
        runtime_secret.grant_read(viewer_function)
        viewer_function.add_to_role_policy(viewer_invoke_policy)

        _lambda.FunctionUrl(
            self,
            id="viewerFunctionUrl",
            function=viewer_function,
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[_lambda.HttpMethod.GET, _lambda.HttpMethod.POST],
            ),
        )


def _build_lambda_code(service_name: str) -> Code:
    requirements_path = requirements_path_for(service_name)
    copy_commands = [
        f"cp -r /asset-input/{source_dir.as_posix()} /asset-output/{source_dir.as_posix()}"
        for source_dir in RUNTIME_SOURCE_DIRECTORIES
    ]
    install_commands = [
        *EXTRA_INSTALL_COMMANDS.get(service_name, []),
        (
            "python -m pip install "
            "--platform manylinux2014_x86_64 "
            "--only-binary=:all: "
            "--python-version 3.11 "
            "--implementation cp "
            f"-r {COMMON_REQUIREMENTS.as_posix()} "
            f"-r {requirements_path.as_posix()} "
            "-t /asset-output"
        ),
        *copy_commands,
    ]
    return Code.from_asset(
        str(PROJECT_ROOT),
        asset_hash_type=AssetHashType.SOURCE,
        bundling=BundlingOptions(
            image=_lambda.Runtime.PYTHON_3_11.bundling_image,
            command=["bash", "-c", " && ".join(install_commands)],
            local=_PythonLocalBundler(service_name),
            user="root:root",
        ),
    )


@jsii.implements(ILocalBundling)
class _PythonLocalBundler:
    def __init__(self, service_name: str) -> None:
        self._service_name = service_name

    def try_bundle(self, output_dir: str, *args, **kwargs) -> bool:
        _ = args, kwargs
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        uv_executable = shutil.which("uv")
        if not uv_executable:
            raise ValueError("uv executable was not found for local bundling")

        requirements_path = PROJECT_ROOT / requirements_path_for(self._service_name)
        common_requirements = PROJECT_ROOT / COMMON_REQUIREMENTS
        if self._service_name == "paper_summarizer":
            subprocess.run(
                [
                    uv_executable,
                    "pip",
                    "install",
                    "sgmllib3k",
                    "arxiv",
                    "--target",
                    str(output_path),
                    "--python-version",
                    "3.11",
                ],
                cwd=PROJECT_ROOT,
                check=True,
            )

        subprocess.run(
            [
                uv_executable,
                "pip",
                "install",
                "--python-platform",
                "x86_64-manylinux2014",
                "--python-version",
                "3.11",
                "-r",
                str(common_requirements),
                "-r",
                str(requirements_path),
                "--target",
                str(output_path),
            ],
            cwd=PROJECT_ROOT,
            check=True,
        )

        for source_dir in RUNTIME_SOURCE_DIRECTORIES:
            shutil.copytree(
                PROJECT_ROOT / source_dir,
                output_path / source_dir,
                dirs_exist_ok=True,
            )
        return True


def _import_runtime_secret(
    scope: Construct,
    runtime_secret_id: str,
) -> secretsmanager.ISecret:
    if runtime_secret_id.startswith("arn:"):
        return secretsmanager.Secret.from_secret_complete_arn(
            scope,
            "NookRuntimeSecret",
            runtime_secret_id,
        )
    return secretsmanager.Secret.from_secret_name_v2(
        scope,
        "NookRuntimeSecret",
        runtime_secret_id,
    )
