"""
Module 2 — AI Client Abstraction Layer
Supports Gemini, OpenAI, Grok (xAI), DeepSeek, TokenRouter (MiniMax-M3),
MiniMax-M3 (free via TokenRouter), Nvidia Nemotron Free (via TokenRouter), and Ollama.
Set the active provider via `set_provider()` or the `LLM_PROVIDER` env var.

V2: Fully async with retry + exponential backoff.
Single provider for all agents — no per-role routing.
"""
import asyncio
import json
import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_active_provider: str = getattr(settings, "llm_provider", "auto")

# ─── Token usage tracking ──────────────────────────────────────────
_current_run_id: str | None = None
_token_usage: dict[str, dict] = {}  # run_id -> {"input": int, "output": int}


def set_run_id(run_id: str) -> None:
    global _current_run_id
    _current_run_id = run_id
    if run_id not in _token_usage:
        _token_usage[run_id] = {"input": 0, "output": 0}


def get_run_tokens(run_id: str | None = None) -> dict:
    rid = run_id or _current_run_id
    if rid and rid in _token_usage:
        return dict(_token_usage[rid])
    return {"input": 0, "output": 0}


def clear_run_tokens(run_id: str | None = None) -> None:
    rid = run_id or _current_run_id
    if rid and rid in _token_usage:
        del _token_usage[rid]


def _add_tokens(input_tokens: int = 0, output_tokens: int = 0) -> None:
    rid = _current_run_id
    if rid:
        if rid not in _token_usage:
            _token_usage[rid] = {"input": 0, "output": 0}
        _token_usage[rid]["input"] += input_tokens
        _token_usage[rid]["output"] += output_tokens


def set_provider(provider: str) -> None:
    global _active_provider
    _active_provider = provider


def get_active_provider() -> str:
    return _active_provider


def _try_heal_json(raw: str) -> str | None:
    """Attempt to repair a truncated JSON string by closing unclosed structures."""
    first = raw.find("{")
    if first == -1:
        return None
    raw = raw[first:]
    depth = 0
    in_str = False
    escape = False
    for i, ch in enumerate(raw):
        if ch == "\\" and in_str:
            escape = True
            continue
        if escape:
            escape = False
            continue
        if ch == '"' and not escape:
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if in_str:
        raw += '"'
    raw += "}" * depth
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        return None


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"(?s)<think>.*?</think>", "", raw)
    raw = re.sub(r"(?s)<think>.*$", "", raw).strip()
    raw = re.sub(r"(?s)```(?:json)?\s*", "", raw)
    candidates: list[str] = []
    i = 0
    while i < len(raw):
        if raw[i] in ("{", "["):
            depth = 0
            in_str = False
            escape = False
            start = i
            ok = False
            for j in range(i, len(raw)):
                ch = raw[j]
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_str:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch in ("{", "["):
                    depth += 1
                elif ch in ("}", "]"):
                    depth -= 1
                    if depth == 0:
                        candidates.append(raw[start: j + 1])
                        i = j + 1
                        ok = True
                        break
            if ok:
                continue
        i += 1
    for cand in reversed(candidates):
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            continue
    if candidates:
        return candidates[0]
    healed = _try_heal_json(raw)
    if healed is not None:
        return healed
    return ""


# ─── Retry helper (exponential backoff) ────────────────────────────────────

async def _retry_with_backoff(coro_factory, max_retries: int = 2, base_delay: float = 0.5):
    """Execute an async call with exponential backoff retry."""
    last_exc = None
    for attempt in range(1 + max_retries):
        try:
            return await coro_factory()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"[AI Client] Attempt {attempt + 1} failed, retrying in {delay:.1f}s: {exc}")
                await asyncio.sleep(delay)
            else:
                logger.error(f"[AI Client] All {max_retries + 1} attempts failed: {exc}")
    raise last_exc


# ─── Async Provider Implementations ────────────────────────────────────────

async def _call_openai_async(prompt: str, system: str, model: str = "gpt-4o-mini") -> str:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=8192,
        )
        if response.usage:
            _add_tokens(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error(f"[AI Client] OpenAI call failed: {exc}")
        return ""


async def _call_gemini_async(prompt: str, system: str, model: str = "gemini-2.5-flash") -> str:
    try:
        import google.generativeai as genai
        genai.configure(api_key=settings.google_api_key)
        model_instance = genai.GenerativeModel(model_name=model, system_instruction=system if system else None)
        response = model_instance.generate_content(prompt, generation_config={"temperature": 0.1, "max_output_tokens": 16384})
        usage = getattr(response, "usage_metadata", None)
        if usage:
            _add_tokens(
                input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            )
        return response.text or ""
    except Exception as exc:
        logger.error(f"[AI Client] Gemini call failed: {exc}")
        return ""


async def _call_grok_async(prompt: str, system: str, model: str = "grok-2") -> str:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.xai_api_key,
            base_url="https://api.x.ai/v1",
        )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=8192,
        )
        if response.usage:
            _add_tokens(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error(f"[AI Client] Grok call failed: {exc}")
        return ""


async def _call_deepseek_async(prompt: str, system: str, model: str = "deepseek-chat") -> str:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
        )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=8192,
        )
        if response.usage:
            _add_tokens(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error(f"[AI Client] DeepSeek call failed: {exc}")
        return ""


async def _call_tokenrouter_model_async(prompt: str, system: str, model: str, label: str) -> str:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            api_key=settings.tokenrouter_api_key,
            base_url=settings.tokenrouter_base_url,
        )
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=8192,
        )
        if response.usage:
            _add_tokens(
                input_tokens=response.usage.prompt_tokens or 0,
                output_tokens=response.usage.completion_tokens or 0,
            )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error(f"[AI Client] {label} call failed: {exc}")
        return ""


async def _call_ollama_async(prompt: str, system: str, model: str = "") -> str:
    try:
        import httpx
        model_name = model or settings.ollama_model
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json={"model": model_name, "messages": messages, "temperature": 0.1, "stream": False},
            )
            resp.raise_for_status()
            data = resp.json()
            _add_tokens(
                input_tokens=data.get("prompt_eval_count", 0) or 0,
                output_tokens=data.get("eval_count", 0) or 0,
            )
            return data.get("message", {}).get("content", "") or ""
    except Exception as exc:
        logger.error(f"[AI Client] Ollama call failed: {exc}")
        return ""


# ─── Provider Registry ─────────────────────────────────────────────────────

_PROVIDER_MAP_ASYNC = {
    "openai": (_call_openai_async, "openai_api_key", True, "gpt-4o-mini"),
    "gemini": (_call_gemini_async, "google_api_key", True, "gemini-2.5-flash"),
    "grok": (_call_grok_async, "xai_api_key", True, "grok-2"),
    "deepseek": (_call_deepseek_async, "deepseek_api_key", True, "deepseek-chat"),
    "tokenrouter": (_call_tokenrouter_model_async, "tokenrouter_api_key", True, settings.tokenrouter_model, "TokenRouter"),
    "minimax": (_call_tokenrouter_model_async, "tokenrouter_api_key", True, settings.minimax_model, "MiniMax-M3"),
    "nvidia": (_call_tokenrouter_model_async, "tokenrouter_api_key", True, settings.nvidia_model, "Nvidia Nemotron"),
    "ollama": (_call_ollama_async, None, False, settings.ollama_model),
}

_FALLBACK_CHAIN = [
    ("TokenRouter", "tokenrouter_api_key", _call_tokenrouter_model_async, settings.tokenrouter_model, "TokenRouter"),
    ("MiniMax-M3", "tokenrouter_api_key", _call_tokenrouter_model_async, settings.minimax_model, "MiniMax-M3"),
    ("Nvidia Nemotron", "tokenrouter_api_key", _call_tokenrouter_model_async, settings.nvidia_model, "Nvidia Nemotron"),
    ("Grok", "xai_api_key", _call_grok_async, "grok-2"),
    ("DeepSeek", "deepseek_api_key", _call_deepseek_async, "deepseek-chat"),
    ("OpenAI", "openai_api_key", _call_openai_async, "gpt-4o-mini"),
    ("Gemini", "google_api_key", _call_gemini_async, "gemini-2.5-flash"),
]


# ─── Main Async LLM Call ──────────────────────────────────────────────────

async def call_llm_async(prompt: str, system: str = "") -> str:
    """Call the active LLM provider with exponential backoff retry."""
    provider = _active_provider

    if provider in _PROVIDER_MAP_ASYNC:
        entry = _PROVIDER_MAP_ASYNC[provider]
        call_fn = entry[0]
        key_attr = entry[1]
        needs_key = entry[2]

        if needs_key and not getattr(settings, key_attr, ""):
            logger.error(f"[AI Client] {provider} selected but {key_attr.upper()} is not set.")
        else:
            args = entry[3:]

            async def _try():
                return await call_fn(prompt, system, *args)

            result = await _retry_with_backoff(_try)
            if result:
                return result
            logger.warning(f"[AI Client] {provider} returned empty, trying alternatives...")

    for name, key_attr, call_fn, *model_args in _FALLBACK_CHAIN:
        if getattr(settings, key_attr, ""):
            async def _try_fallback(fn=call_fn, args=model_args):
                return await fn(prompt, system, *args)
            result = await _retry_with_backoff(_try_fallback)
            if result:
                return result
            logger.warning(f"[AI Client] {name} returned empty, trying next...")

    return await _retry_with_backoff(
        lambda: _call_ollama_async(prompt, system, settings.ollama_model)
    )


async def call_llm_json_async(prompt: str, system: str = "", max_retries: int = 2) -> dict[str, Any]:
    """Call LLM and parse JSON response, with retries on parse failure."""
    RETRY_PROMPT_SUFFIX = (
        "\n\n---\nYOUR PREVIOUS RESPONSE COULD NOT BE PARSED AS VALID JSON.\n"
        "Return ONLY a raw JSON object — NO markdown fences (no ```), NO text outside the JSON."
    )

    for attempt in range(1 + max_retries):
        raw = await call_llm_async(prompt, system)
        if not raw:
            logger.warning(f"[AI Client] LLM returned empty (attempt {attempt + 1})")
            prompt += RETRY_PROMPT_SUFFIX
            continue
        cleaned = _clean_json(raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning(
                f"[AI Client] JSON parse failed (attempt {attempt + 1}): {exc}\n"
                f"  Cleaned text: {cleaned[:400]}"
            )
            prompt += RETRY_PROMPT_SUFFIX

    logger.error(f"[AI Client] All {max_retries + 1} JSON parse attempts failed.")
    return {}


# ─── Legacy sync wrappers (keep for backward compat) ───────────────────────

def call_llm(prompt: str, system: str = "") -> str:
    """Legacy sync wrapper — runs async in a temporary event loop."""
    return asyncio.run(call_llm_async(prompt, system))


def call_llm_json(prompt: str, system: str = "", max_retries: int = 2) -> dict[str, Any]:
    """Legacy sync wrapper — runs async in a temporary event loop."""
    return asyncio.run(call_llm_json_async(prompt, system, max_retries))
