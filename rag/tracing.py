import os
from functools import wraps
from typing import Callable


def is_langsmith_enabled() -> bool:
    return os.getenv("LANGSMITH_TRACING", "false").lower() == "true"


def trace_step(step_name: str):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if is_langsmith_enabled():
                print(f"[LangSmith Trace] Starting step: {step_name}")

            result = func(*args, **kwargs)

            if is_langsmith_enabled():
                print(f"[LangSmith Trace] Finished step: {step_name}")

            return result

        return wrapper

    return decorator