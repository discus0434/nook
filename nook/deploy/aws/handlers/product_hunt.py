from typing import Any

from nook.deploy.aws.handlers.common import run_collector_lambda


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    _ = context
    return run_collector_lambda("product_hunt", event)
