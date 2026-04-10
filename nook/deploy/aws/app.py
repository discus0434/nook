import os

import aws_cdk as cdk
from dotenv import load_dotenv

from nook.deploy.aws.runtime_config import AwsStackConfig
from nook.deploy.aws.stack import NookStack


def build_cdk_app() -> cdk.App:
    load_dotenv()
    app = cdk.App()
    NookStack(
        app,
        construct_id="NookStack",
        config=AwsStackConfig.from_env(os.environ),
        env=cdk.Environment(region=os.getenv("CDK_DEFAULT_REGION")),
    )
    return app


def main() -> None:
    build_cdk_app().synth()


if __name__ == "__main__":
    main()
