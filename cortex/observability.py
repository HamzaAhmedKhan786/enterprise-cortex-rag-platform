"""Actual dependency/configuration states; no false claim of a connected service."""
import importlib.util
import os
from pathlib import Path

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ.setdefault("DEEPEVAL_HOME", str(Path("data/private/deepeval").resolve()))

from cortex import store


def readiness(owner):
    return [
        {"component": "Langfuse", "installed": bool(importlib.util.find_spec("langfuse")),
         "configured": bool(os.getenv("LANGFUSE_HOST") and os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")),
         "state": "Metadata tracing enabled when credentials are configured" if os.getenv("LANGFUSE_ENABLED", "true").lower() == "true" else "Disabled by operator"},
        {"component": "DeepEval", "installed": bool(importlib.util.find_spec("deepeval")), "configured": True,
         "state": "Local citation evaluation; telemetry disabled; no cloud judge"},
    ]


def check_langfuse(owner):
    if not all(os.getenv(k) for k in ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")):
        raise ValueError("Langfuse SDK is available, but LANGFUSE_HOST, PUBLIC_KEY and SECRET_KEY must point to a real Langfuse deployment.")
    from langfuse import get_client
    if not get_client().auth_check():
        raise ValueError("Langfuse authentication failed. Check the configured host and keys.")
    store.audit(owner, "langfuse_connection_verified")
    return {"authenticated": True, "payload_policy": "Run metadata only; no prompts, documents or identities"}


def evaluate_citations(answer, source_count):
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    from evaluation.evidence_metric import EvidenceCitationMetric
    from deepeval.test_case import LLMTestCase
    metric = EvidenceCitationMetric()
    case = LLMTestCase(input="Check reference validity", actual_output=answer, retrieval_context=[f"Evidence {i + 1}" for i in range(source_count)])
    score = metric.measure(case)
    return {"score": score, "passed": metric.is_successful(), "reason": metric.reason, "scope": "Citation IDs only; not semantic faithfulness"}


def evaluation_smoke(owner):
    result = evaluate_citations("Refunds take five business days. [1]", 1)
    store.audit(owner, "deepeval_smoke_completed", detail={"passed": result["passed"], "score": result["score"]})
    return result
