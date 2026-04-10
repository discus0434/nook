import os
import traceback
from typing import Any

from nook.services.registry import run_collector


def run_collector_lambda(service_name: str, event: dict[str, Any]) -> dict[str, Any]:
    print(f"Lambda event for {service_name}: {event}")
    os.environ.setdefault("NOOK_RUNTIME_MODE", "aws")
    os.environ.setdefault("NOOK_STORAGE_BACKEND", "s3")

    try:
        run_collector(service_name)
    except Exception as error:
        print(traceback.format_exc())
        raise RuntimeError(f"Collector {service_name} failed") from error

    return {
        "statusCode": 200,
        "message": f"{service_name} completed successfully",
    }
