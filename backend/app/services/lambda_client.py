import json
import logging

import boto3

from app.core.config import settings
from app.services.explanation import generate_explanation

logger = logging.getLogger(__name__)

_lambda_client = None


def is_enabled() -> bool:
    return bool(settings.explanation_lambda_function_name)


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda", region_name=settings.aws_region)
    return _lambda_client


def generate_explanation_via_lambda(title: str, transcript: str, ocr_text: str) -> str:
    """Same contract as generate_explanation() — never raises. Tries the
    AWS Lambda function first, falls back to the in-process implementation
    on ANY invoke-path failure: no instance profile attached, function not
    deployed in this environment, network error, or (in local dev) no AWS
    credentials at all. Every environment that works today keeps working
    identically; only a correctly deployed and IAM-authorized EC2 instance
    actually offloads the call.
    """
    if not is_enabled():
        return generate_explanation(title, transcript, ocr_text)

    payload = {"title": title, "transcript": transcript, "ocr_text": ocr_text}
    try:
        response = _get_lambda_client().invoke(
            FunctionName=settings.explanation_lambda_function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload).encode("utf-8"),
        )
        if response.get("FunctionError"):
            raise RuntimeError(f"Lambda FunctionError: {response['FunctionError']}")
        body = json.loads(response["Payload"].read())
        return body.get("explanation") or ""
    except Exception:
        logger.warning("Explanation Lambda invoke failed, falling back to in-process generation", exc_info=True)
        return generate_explanation(title, transcript, ocr_text)
