"""Shared LLM helper — uses Claude API when available, Ollama fallback."""

import os
import re
import time


# Retry settings for transient API errors (529 Overloaded, 5xx, etc.)
MAX_RETRIES = 5
INITIAL_BACKOFF = 2  # seconds


def _strip_think_blocks(text: str) -> str:
    """Remove <think>...</think> blocks from Ollama reasoning models."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _detect_provider() -> tuple[bool, str]:
    """Return (use_claude, model_name) based on env vars."""
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    text_model = os.getenv("TEXT_MODEL", "")

    if text_model:
        use_claude = text_model.startswith("claude")
    elif anthropic_key:
        use_claude = True
        text_model = "claude-sonnet-4-20250514"
    else:
        use_claude = False
        text_model = "qwen3:8b"

    return use_claude, text_model


def invoke_llm(prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    """Send a text prompt to the best available LLM and return the response.

    Provider auto-detection:
      - ANTHROPIC_API_KEY set + TEXT_MODEL unset or starts with "claude"
        -> Anthropic Claude API (with retry on 529/5xx)
      - Otherwise -> Ollama via ChatOllama with TEXT_MODEL (default qwen3:8b)

    Override with TEXT_MODEL env var:
      - "claude-sonnet-4-20250514" -> forces Claude
      - "qwen3:8b" -> forces Ollama
    """
    use_claude, text_model = _detect_provider()

    provider = "Claude API" if use_claude else "Ollama"
    print(f"  LLM: {text_model} ({provider})")

    if use_claude:
        import anthropic

        client = anthropic.Anthropic()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.messages.create(
                    model=text_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.content[0].text
            except (anthropic.OverloadedError, anthropic.InternalServerError,
                    anthropic.RateLimitError) as e:
                if attempt == MAX_RETRIES:
                    raise
                wait = INITIAL_BACKOFF * (2 ** (attempt - 1))
                print(f"  Retry {attempt}/{MAX_RETRIES} after {type(e).__name__} "
                      f"— waiting {wait}s...")
                time.sleep(wait)
    else:
        from langchain_core.messages import HumanMessage
        from langchain_ollama import ChatOllama

        llm = ChatOllama(model=text_model, temperature=temperature,
                         num_predict=max_tokens)
        response = llm.invoke([HumanMessage(content=prompt)])
        return _strip_think_blocks(response.content)
