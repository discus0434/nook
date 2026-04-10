import os

from mangum import Mangum

from nook.services.viewer.app import build_app_from_env

os.environ.setdefault("NOOK_RUNTIME_MODE", "aws")
os.environ.setdefault("NOOK_STORAGE_BACKEND", "s3")

lambda_handler = Mangum(build_app_from_env())
