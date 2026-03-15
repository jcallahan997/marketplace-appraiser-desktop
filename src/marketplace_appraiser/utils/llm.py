"""Shared LLM helper — uses Claude API when available, Ollama fallback.

All Claude API calls are instrumented with Langfuse for token tracking and
cost reporting when a Langfuse trace is active (see langfuse_ctx.py).
"""

import os
import re
import time

from marketplace_appraiser.utils.langfuse_ctx import calculate_cost, get_trace

# Retry settings for transient API errors (529 Overloaded, 5xx, etc.)
MAX_RETRIES = 5
INITIAL_BACKOFF = 2  # seconds


def _call_claude(
    prompt: str | list,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    tier: str = "standard",
) -> str:
    """Make a Claude API call with retry and Langfuse instrumentation.

    Args:
        prompt: Text prompt string, or list of content blocks (for vision).
        model: Anthropic model name.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature.
        tier: Label for Langfuse (e.g. "standard", "light", "premium", "vision").

    Returns:
        The generated text response.
    """
    import anthropic

    client = anthropic.Anthropic()

    # Build the messages payload
    messages = [{"role": "user", "content": prompt}]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=messages,
            )
            output_text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

            # Report to Langfuse
            trace = get_trace()
            if trace:
                try:
                    cost = calculate_cost(model, input_tokens, output_tokens)
                    usage = {
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": input_tokens + output_tokens,
                    }
                    if cost is not None:
                        usage["total_cost"] = cost
                    input_display = (
                        prompt if isinstance(prompt, str)
                        else f"[vision: {len(prompt)} content blocks]"
                    )
                    trace.generation(
                        name=f"llm-{tier}",
                        model=model,
                        input=input_display[:3000],
                        output=output_text[:3000],
                        usage=usage,
                        metadata={
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                except Exception:
                    pass  # Never break pipeline for observability

            return output_text
        except (anthropic.OverloadedError, anthropic.InternalServerError,
                anthropic.RateLimitError) as e:
            if attempt == MAX_RETRIES:
                raise
            wait = INITIAL_BACKOFF * (2 ** (attempt - 1))
            print(f"  Retry {attempt}/{MAX_RETRIES} after {type(e).__name__} "
                  f"— waiting {wait}s...")
            time.sleep(wait)


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from Ollama reasoning models."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _detect_provider(light: bool = False) -> tuple[bool, str]:
    """Return (use_claude, model_name) based on env vars.

    When *light* is True, prefer the cheaper LIGHT_MODEL (default Haiku)
    for simple classification / extraction tasks.
    """
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    text_model = os.getenv("TEXT_MODEL", "")
    light_model = os.getenv("LIGHT_MODEL", "claude-haiku-4-5-20251001")

    if light and anthropic_key:
        return True, light_model

    if text_model:
        use_claude = text_model.startswith("claude")
    elif anthropic_key:
        use_claude = True
        text_model = "claude-sonnet-4-20250514"
    else:
        use_claude = False
        text_model = "qwen3:8b"

    return use_claude, text_model


def invoke_llm_premium(prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """High-quality LLM call using Opus (or PREMIUM_MODEL env var).

    Use for the highest-stakes outputs where reasoning quality matters most
    (e.g. final price assessment and BUY/NEGOTIATE/PASS recommendation).
    Falls back to the default TEXT_MODEL if not using Claude.
    """
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    premium_model = os.getenv("PREMIUM_MODEL", "claude-sonnet-4-20250514")

    if not anthropic_key:
        return invoke_llm(prompt, temperature=temperature, max_tokens=max_tokens)

    print(f"  LLM-premium: {premium_model} (Claude API)")
    return _call_claude(
        prompt, model=premium_model,
        max_tokens=max_tokens, temperature=temperature, tier="premium",
    )


def invoke_llm(prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Send a text prompt to the best available LLM and return the response."""
    use_claude, text_model = _detect_provider()

    provider = "Claude API" if use_claude else "Ollama"
    print(f"  LLM: {text_model} ({provider})")

    if use_claude:
        return _call_claude(
            prompt, model=text_model,
            max_tokens=max_tokens, temperature=temperature, tier="standard",
        )
    else:
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama

        llm = ChatOllama(model=text_model, temperature=temperature,
                         num_predict=max_tokens)
        response = llm.invoke([HumanMessage(content=prompt)])
        return _strip_think_blocks(response.content)


def invoke_llm_light(prompt: str, temperature: float = 0.2,
                     max_tokens: int = 1024) -> str:
    """Lightweight LLM call using Haiku (or LIGHT_MODEL env var)."""
    use_claude, model = _detect_provider(light=True)

    provider = "Claude API" if use_claude else "Ollama"
    print(f"  LLM-light: {model} ({provider})")

    if use_claude:
        return _call_claude(
            prompt, model=model,
            max_tokens=max_tokens, temperature=temperature, tier="light",
        )
    else:
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama

        llm = ChatOllama(model=model, temperature=temperature,
                         num_predict=max_tokens)
        response = llm.invoke([HumanMessage(content=prompt)])
        return _strip_think_blocks(response.content)
