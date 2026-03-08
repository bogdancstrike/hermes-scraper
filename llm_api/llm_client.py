"""
LLM client abstraction.

Priority order (first configured wins):
  1. Claude (Anthropic) — set ANTHROPIC_API_KEY
  2. OpenAI-compatible (vLLM / OpenAI) — set OPENAI_API_KEY or LLM_BASE_URL
"""
from __future__ import annotations

import json
import os
import re
import time

from shared.logging import get_logger
from shared.metrics import llm_duration_seconds, llm_requests_total, llm_tokens_sent_total

logger = get_logger("llm_client")

# ── Claude / Anthropic ────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")

# ── OpenAI / vLLM fallback ────────────────────────────────────
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:8001/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "meta-llama/Llama-3.1-8B-Instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "none")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# ── Shared settings ───────────────────────────────────────────
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1024"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))


class LLMClient:
    """
    Unified LLM client.
    Tries Claude first (if ANTHROPIC_API_KEY set), then OpenAI/vLLM.
    """

    def __init__(self):
        self._anthropic = None
        self._openai_client = None

        # Build Claude client
        if ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._anthropic = anthropic.AsyncAnthropic(
                    api_key=ANTHROPIC_API_KEY,
                    timeout=LLM_TIMEOUT,
                )
                logger.info("llm_backend_claude", model=CLAUDE_MODEL)
            except ImportError:
                logger.warning("anthropic_sdk_missing", hint="pip install anthropic")

        # Build OpenAI-compatible client (vLLM or OpenAI)
        if not self._anthropic:
            try:
                from openai import AsyncOpenAI
                if OPENAI_API_KEY:
                    self._openai_client = AsyncOpenAI(
                        api_key=OPENAI_API_KEY, timeout=LLM_TIMEOUT
                    )
                    self._openai_model = OPENAI_MODEL
                    logger.info("llm_backend_openai", model=OPENAI_MODEL)
                else:
                    self._openai_client = AsyncOpenAI(
                        base_url=LLM_BASE_URL,
                        api_key=LLM_API_KEY,
                        timeout=LLM_TIMEOUT,
                    )
                    self._openai_model = LLM_MODEL
                    logger.info("llm_backend_vllm", model=LLM_MODEL, base_url=LLM_BASE_URL)
            except ImportError:
                logger.warning("openai_sdk_missing", hint="pip install openai")

        if not self._anthropic and not self._openai_client:
            raise RuntimeError(
                "No LLM configured. Set ANTHROPIC_API_KEY (recommended) "
                "or OPENAI_API_KEY or LLM_BASE_URL in .env"
            )

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        endpoint_label: str = "generic",
    ) -> tuple[str, str]:
        """
        Call the configured LLM. Returns (response_text, model_name).
        """
        approx_tokens = (len(system_prompt) + len(user_prompt)) // 4
        llm_tokens_sent_total.labels(endpoint=endpoint_label).inc(approx_tokens)

        if self._anthropic:
            return await self._call_claude(system_prompt, user_prompt, endpoint_label)
        return await self._call_openai(system_prompt, user_prompt, endpoint_label)

    async def _call_claude(
        self, system_prompt: str, user_prompt: str, endpoint_label: str
    ) -> tuple[str, str]:
        start = time.monotonic()
        try:
            response = await self._anthropic.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=LLM_MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = response.content[0].text if response.content else ""
            duration = time.monotonic() - start
            llm_duration_seconds.labels(endpoint=endpoint_label).observe(duration)
            llm_requests_total.labels(
                endpoint=endpoint_label, model=CLAUDE_MODEL, status="success"
            ).inc()
            logger.debug("claude_call_success", model=CLAUDE_MODEL, duration_ms=int(duration * 1000))
            return text, CLAUDE_MODEL
        except Exception as exc:
            duration = time.monotonic() - start
            llm_requests_total.labels(
                endpoint=endpoint_label, model=CLAUDE_MODEL, status="error"
            ).inc()
            logger.error("claude_call_failed", error=str(exc), duration_ms=int(duration * 1000))
            raise

    async def _call_openai(
        self, system_prompt: str, user_prompt: str, endpoint_label: str
    ) -> tuple[str, str]:
        model = self._openai_model
        start = time.monotonic()
        try:
            response = await self._openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
            )
            text = response.choices[0].message.content or ""
            duration = time.monotonic() - start
            llm_duration_seconds.labels(endpoint=endpoint_label).observe(duration)
            llm_requests_total.labels(endpoint=endpoint_label, model=model, status="success").inc()
            logger.debug("openai_call_success", model=model, duration_ms=int(duration * 1000))
            return text, model
        except Exception as exc:
            duration = time.monotonic() - start
            llm_requests_total.labels(endpoint=endpoint_label, model=model, status="error").inc()
            logger.error("openai_call_failed", model=model, error=str(exc))
            raise

    @staticmethod
    def parse_json_response(text: str) -> dict:
        """
        Robustly extract JSON from LLM response.
        Handles markdown code blocks, leading/trailing prose.
        """
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        text = text.rstrip("`").strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.warning("json_parse_failed", text_preview=text[:200])
        return {}


# Singleton
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
