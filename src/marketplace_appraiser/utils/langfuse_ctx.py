"""Thread-local Langfuse trace context for instrumentation.

Usage in server.py:
    from marketplace_appraiser.utils.langfuse_ctx import set_trace, clear_trace

    trace = langfuse_client.trace(name=..., metadata=...)
    set_trace(trace)
    try:
        result = app_graph.invoke(...)
    finally:
        clear_trace()

Usage in llm.py / search.py / vision.py:
    from marketplace_appraiser.utils.langfuse_ctx import get_trace

    trace = get_trace()
    if trace:
        trace.generation(name=..., model=..., usage=...)
"""

import threading

_thread_local = threading.local()


def set_trace(trace) -> None:
    """Store the Langfuse trace for the current pipeline thread."""
    _thread_local.langfuse_trace = trace


def get_trace():
    """Get the current thread's Langfuse trace, or None if not set."""
    return getattr(_thread_local, "langfuse_trace", None)


def clear_trace() -> None:
    """Remove the trace reference for the current thread."""
    _thread_local.langfuse_trace = None


# Anthropic model pricing (per million tokens, USD)
# Updated: 2025-06
MODEL_PRICING = {
    # Sonnet 4
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    # Haiku 3.5
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # Opus 4
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    # Sonnet 3.5 v2
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    # Sonnet 3.5
    "claude-3-5-sonnet-20240620": {"input": 3.0, "output": 15.0},
    # Haiku 3
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Calculate USD cost for a given model and token counts.

    Returns None if model pricing is unknown.
    """
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return None
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
