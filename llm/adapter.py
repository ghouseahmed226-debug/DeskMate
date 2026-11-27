"""Provider-independent model adapters with offline rule-based fallback."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from core.config import get_settings


class ModelResponse(BaseModel):
    text: str
    structured: Optional[Dict[str, Any]] = None
    provider: str
    model: str
    usage: Dict[str, int] = Field(default_factory=dict)


class BaseModelAdapter(ABC):
    provider_name: str = "base"
    model_name: str = "unknown"

    @abstractmethod
    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> ModelResponse:
        """Generates a text completion from the configured provider."""

    def generate_json(self, system_prompt: str, user_prompt: str) -> ModelResponse:
        """Generates a structured JSON completion with safe parsing."""
        res = self.generate_text(
            system_prompt=system_prompt + "\nRespond strictly with valid JSON.",
            user_prompt=user_prompt,
            temperature=0.0,
        )
        raw = res.text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
        try:
            res.structured = json.loads(raw)
        except json.JSONDecodeError:
            res.structured = None
        return res


class OfflineRuleAdapter(BaseModelAdapter):
    """Zero-dependency deterministic adapter used when no paid LLM API is configured."""

    provider_name = "offline"
    model_name = "deskmate-deterministic-v2"

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> ModelResponse:
        return ModelResponse(
            text=user_prompt.strip(),
            structured=None,
            provider=self.provider_name,
            model=self.model_name,
            usage={"prompt_tokens": 0, "completion_tokens": 0},
        )


class GeminiModelAdapter(BaseModelAdapter):
    provider_name = "gemini"

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash") -> None:
        self.api_key = api_key
        self.model_name = model_name or "gemini-2.0-flash"

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> ModelResponse:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            resp = client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                ),
            )
            return ModelResponse(
                text=resp.text or "",
                provider=self.provider_name,
                model=self.model_name,
            )
        except ImportError:
            import google.generativeai as legacy_genai

            legacy_genai.configure(api_key=self.api_key)
            model = legacy_genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=system_prompt,
            )
            resp = model.generate_content(user_prompt)
            return ModelResponse(
                text=getattr(resp, "text", "") or "",
                provider=self.provider_name,
                model=self.model_name,
            )


class OpenAIModelAdapter(BaseModelAdapter):
    provider_name = "openai"

    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini") -> None:
        self.api_key = api_key
        self.model_name = model_name or "gpt-4o-mini"

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> ModelResponse:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model_name,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = resp.choices[0].message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": int(resp.usage.prompt_tokens or 0),
                "completion_tokens": int(resp.usage.completion_tokens or 0),
            }
        return ModelResponse(
            text=content,
            provider=self.provider_name,
            model=self.model_name,
            usage=usage,
        )


class AnthropicModelAdapter(BaseModelAdapter):
    provider_name = "anthropic"

    def __init__(self, api_key: str, model_name: str = "claude-3-5-sonnet-latest") -> None:
        self.api_key = api_key
        self.model_name = model_name or "claude-3-5-sonnet-latest"

    def generate_text(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> ModelResponse:
        from anthropic import Anthropic

        client = Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model_name,
            max_tokens=1024,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = "".join(getattr(block, "text", "") for block in resp.content)
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": int(getattr(resp.usage, "input_tokens", 0) or 0),
                "completion_tokens": int(getattr(resp.usage, "output_tokens", 0) or 0),
            }
        return ModelResponse(
            text=text,
            provider=self.provider_name,
            model=self.model_name,
            usage=usage,
        )


class ModelFactory:
    """Selects the configured model provider with clean offline fallback."""

    @staticmethod
    def create(provider: Optional[str] = None, model_name: Optional[str] = None) -> BaseModelAdapter:
        settings = get_settings()
        chosen = (provider or settings.llm_provider or "offline").strip().lower()
        chosen_model = model_name or settings.llm_model

        if chosen == "gemini" and settings.gemini_api_key:
            return GeminiModelAdapter(settings.gemini_api_key, chosen_model or "gemini-2.0-flash")
        if chosen == "openai" and settings.openai_api_key:
            return OpenAIModelAdapter(settings.openai_api_key, chosen_model or "gpt-4o-mini")
        if chosen == "anthropic" and settings.anthropic_api_key:
            return AnthropicModelAdapter(settings.anthropic_api_key, chosen_model or "claude-3-5-sonnet-latest")
        return OfflineRuleAdapter()
