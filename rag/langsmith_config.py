import os


def enable_langsmith():
    os.environ["LANGSMITH_TRACING"] = os.getenv("LANGSMITH_TRACING", "false")
    os.environ["LANGSMITH_PROJECT"] = os.getenv(
        "LANGSMITH_PROJECT",
        "enterprise-cortex-rag"
    )