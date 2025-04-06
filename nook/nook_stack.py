import os
from dataclasses import dataclass

from aws_cdk import AssetHashType, BundlingOptions, Duration, RemovalPolicy, Stack, aws_iam as iam
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_s3 as s3
from aws_cdk.aws_lambda import Code, Function, FunctionUrl, LayerVersion, Runtime
from constructs import Construct


@dataclass
class NookNames:
    hacker_news: str = "hacker_news"
    paper_summarizer: str = "paper_summarizer"
    reddit_explorer: str = "reddit_explorer"
    tech_feed: str = "tech_feed"
    github_trending: str = "github_trending"
    viewer: str = "viewer"


class NookStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, env_vars: dict[str, str], **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        information_retriever_names = NookNames()
        root_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lambda")

        # s3 bucket for storing the historical data
        s3_bucket = s3.Bucket(
            self,
            id="NookBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Create the common utils layer
        common_utils_layer = LayerVersion(
            self,
            "CommonUtilsLayer",
            code=Code.from_asset(
                os.path.join(root_dir, "common"),
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "&&".join(
                            [
                                "python -m pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 --implementation cp -r requirements.txt -t /asset-output/python",
                                "cp -r python /asset-output/",
                            ]
                        ),
                    ],
                    user="root:root",
                ),
            ),
            compatible_runtimes=[Runtime.PYTHON_3_11],
            description="Common dependencies",
        )

        lambda_functions: dict[str, Function | _lambda.DockerImageFunction] = {}
        function_urls: dict[str, FunctionUrl] = {}
        viewer_environment = {
            "BUCKET_NAME": s3_bucket.bucket_name,
            "GEMINI_API_KEY": env_vars["GEMINI_API_KEY"],
            "REDDIT_CLIENT_ID": env_vars["REDDIT_CLIENT_ID"],
            "REDDIT_CLIENT_SECRET": env_vars["REDDIT_CLIENT_SECRET"],
            "REDDIT_USER_AGENT": env_vars["REDDIT_USER_AGENT"],
        }
        viewer_invoke_policy = iam.PolicyStatement(
            actions=["lambda:InvokeFunction"],
            resources=[],
        )

        for i, app_name in enumerate(information_retriever_names.__dict__.values()):
            lambda_environment = {
                "BUCKET_NAME": s3_bucket.bucket_name,
                "GEMINI_API_KEY": env_vars["GEMINI_API_KEY"],
                "REDDIT_CLIENT_ID": env_vars["REDDIT_CLIENT_ID"],
                "REDDIT_CLIENT_SECRET": env_vars["REDDIT_CLIENT_SECRET"],
                "REDDIT_USER_AGENT": env_vars["REDDIT_USER_AGENT"],
            }

            if app_name == information_retriever_names.viewer:
                # Viewer function uses its own environment later
                pass
            elif app_name == information_retriever_names.tech_feed:
                lambda_function = _lambda.DockerImageFunction(
                    self,
                    id=app_name,
                    code=_lambda.DockerImageCode.from_image_asset(
                        directory=os.path.join(root_dir, app_name)
                    ),
                    environment=lambda_environment,
                    timeout=Duration.seconds(900),
                )
            else:
                installation_command = "python -m pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 --implementation cp -r requirements.txt -t /asset-output"
                if app_name == information_retriever_names.paper_summarizer:
                    installation_command = (
                        "python -m pip install sgmllib3k arxiv -t /asset-output && "
                        + installation_command
                    )
                lambda_function = Function(
                    self,
                    id=app_name,
                    runtime=Runtime.PYTHON_3_11,
                    code=Code.from_asset(
                        os.path.join(root_dir, app_name),
                        asset_hash_type=AssetHashType.SOURCE,
                        bundling=BundlingOptions(
                            image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                            command=[
                                "bash",
                                "-c",
                                "&&".join(
                                    [
                                        installation_command,
                                        "cp -rT /asset-input /asset-output",
                                    ]
                                ),
                            ],
                            user="root:root",
                        ),
                    ),
                    handler=f"{app_name}.lambda_handler",
                    environment=lambda_environment,
                    memory_size=2048
                    if app_name == information_retriever_names.paper_summarizer
                    else 128,
                    timeout=Duration.seconds(900),
                    layers=[common_utils_layer],
                )

            lambda_functions[app_name] = lambda_function
            s3_bucket.grant_read_write(lambda_function)
            viewer_invoke_policy.add_resources(lambda_function.function_arn)
            viewer_environment[f"{app_name.upper()}_FUNCTION_ARN"] = lambda_function.function_arn

            # UTC 0:00 (JST 9:00) から10分おき
            daily_0_oclock_cron_rule = events.Rule(
                self,
                id=f"Daily0OClockRule{i}",
                schedule=events.Schedule.cron(
                    minute=f"{10 * i}", hour="0", month="*", week_day="*", year="*"
                ),
            )
            daily_0_oclock_cron_rule.add_target(
                targets.LambdaFunction(lambda_function)
            )

        # Create Viewer Lambda last, passing other function URLs
        viewer_function = Function(
            self,
            id=information_retriever_names.viewer,
            runtime=Runtime.PYTHON_3_11,
            code=Code.from_asset(
                os.path.join(root_dir, information_retriever_names.viewer),
                asset_hash_type=AssetHashType.SOURCE,
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "&&".join(
                            [
                                "python -m pip install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.11 --implementation cp -r requirements.txt -t /asset-output",
                                "cp -rT /asset-input /asset-output",
                            ]
                        ),
                    ],
                    user="root:root",
                ),
            ),
            handler=f"{information_retriever_names.viewer}.lambda_handler",
            environment=viewer_environment, # Pass the collected env vars
            timeout=Duration.seconds(30), # Viewer might not need long timeout
            layers=[common_utils_layer],
        )
        lambda_functions[information_retriever_names.viewer] = viewer_function
        s3_bucket.grant_read_write(viewer_function) # Grant S3 access to viewer
        viewer_function.add_to_role_policy(viewer_invoke_policy)

        # Re-add Function URL creation for the viewer function
        viewer_function_url = _lambda.FunctionUrl(
            self,
            id=f"{information_retriever_names.viewer}FunctionUrl", # Explicitly create FunctionUrl with unique ID
            function=viewer_function,
            auth_type=_lambda.FunctionUrlAuthType.NONE,
            cors=_lambda.FunctionUrlCorsOptions(
                allowed_origins=["*"], # Be cautious with "*" in production
                allowed_methods=[
                    _lambda.HttpMethod.GET,
                    _lambda.HttpMethod.POST,
                ],
             ),
         )
        function_urls[information_retriever_names.viewer] = viewer_function_url
