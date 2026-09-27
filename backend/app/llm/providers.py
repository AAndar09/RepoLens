import json
import time
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.llm.base import (
    AsyncProviderMixin,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMMalformedResponseError,
    LLMMessage,
    LLMProviderError,
    LLMRateLimitError,
    LLMResult,
    LLMUnavailableError,
    LLMUsage,
    OutputModel,
)


def _raise_http_error(provider: str, model: str, exc: httpx.HTTPError) -> None:
    prefix = f"{provider}/{model}"
    if isinstance(exc, httpx.TimeoutException):
        raise LLMUnavailableError(f"{prefix} timed out") from exc
    if isinstance(exc, httpx.RequestError):
        raise LLMUnavailableError(f"{prefix} could not be reached") from exc
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = ""
        try:
            error = exc.response.json().get("error", {})
            message = error.get("message") if isinstance(error, dict) else None
            if isinstance(message, str):
                detail = f": {message[:500]}"
            failed_generation = error.get("failed_generation") if isinstance(error, dict) else None
            if isinstance(failed_generation, str):
                detail += f"; failed_generation={failed_generation[:500]}"
        except (ValueError, AttributeError):
            pass
        if status in {401, 403}:
            raise LLMAuthenticationError(f"{prefix} rejected its API credentials") from exc
        if status == 429:
            raise LLMRateLimitError(f"{prefix} rate limit was reached") from exc
        if status >= 500:
            raise LLMUnavailableError(f"{prefix} returned service error {status}") from exc
        raise LLMProviderError(
            f"{prefix} rejected the request with status {status}{detail}"
        ) from exc
    raise LLMProviderError(f"{prefix} request failed") from exc


def _validate(content: str, output_type: type[OutputModel], provider: str) -> OutputModel:
    try:
        return output_type.model_validate_json(content)
    except (ValueError, ValidationError) as exc:
        raise LLMMalformedResponseError(
            f"{provider} returned invalid {output_type.__name__} JSON"
        ) from exc


class GeminiProvider(AsyncProviderMixin):
    provider_name = "gemini"

    def __init__(
        self,
        model: str,
        api_key: str | None,
        timeout: float,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def _call(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any] | None,
        max_output_tokens: int,
    ) -> LLMResult:
        if not self.api_key:
            raise LLMConfigurationError("Gemini is selected but REPOLENS_GEMINI_API_KEY is unset")
        system = "\n".join(item.content for item in messages if item.role == "system")
        user = "\n".join(item.content for item in messages if item.role != "system")
        generation: dict[str, Any] = {
            "temperature": 0,
            "maxOutputTokens": max_output_tokens,
        }
        if schema is not None:
            generation.update(
                {"responseMimeType": "application/json", "responseJsonSchema": schema}
            )
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        started = time.perf_counter()
        try:
            response = self.client.post(
                f"{self.base_url}/v1beta/models/{quote(self.model, safe='')}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _raise_http_error(self.provider_name, self.model, exc)
        duration = round((time.perf_counter() - started) * 1000)
        try:
            payload = response.json()
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
            usage = payload.get("usageMetadata", {})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMMalformedResponseError("Gemini returned a malformed response") from exc
        return LLMResult(
            content=content,
            provider=self.provider_name,
            model=self.model,
            duration_ms=duration,
            usage=LLMUsage(
                usage.get("promptTokenCount"),
                usage.get("candidatesTokenCount"),
                usage.get("totalTokenCount"),
            ),
        )

    def invoke(self, messages: list[LLMMessage], *, max_output_tokens: int = 512) -> LLMResult:
        return self._call(messages, None, max_output_tokens)

    def invoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]:
        result = self._call(messages, output_type.model_json_schema(), max_output_tokens)
        return _validate(result.content, output_type, self.provider_name), result


class OpenAICompatibleProvider(AsyncProviderMixin):
    def __init__(
        self,
        provider_name: str,
        model: str,
        api_key: str | None,
        timeout: float,
        base_url: str,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)
        self.extra_headers = extra_headers or {}

    def _call(
        self,
        messages: list[LLMMessage],
        schema_name: str | None,
        schema: dict[str, Any] | None,
        max_output_tokens: int,
    ) -> LLMResult:
        if not self.api_key:
            key_name = f"REPOLENS_{self.provider_name.upper()}_API_KEY"
            raise LLMConfigurationError(f"{self.provider_name} is selected but {key_name} is unset")
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [item.__dict__ for item in messages],
            "temperature": 0,
            "max_tokens": max_output_tokens,
        }
        if schema is not None:
            if self.provider_name == "groq":
                body["response_format"] = {"type": "json_object"}
                body["messages"][-1]["content"] += (
                    "\nThe JSON response must match this schema:\n"
                    + json.dumps(schema, separators=(",", ":"))
                )
            else:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": False, "schema": schema},
                }
            if self.provider_name == "openrouter":
                body["provider"] = {"require_parameters": True}
        headers = {"Authorization": f"Bearer {self.api_key}", **self.extra_headers}
        started = time.perf_counter()
        try:
            response = self.client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=body
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _raise_http_error(self.provider_name, self.model, exc)
        duration = round((time.perf_counter() - started) * 1000)
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage", {})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMMalformedResponseError(
                f"{self.provider_name} returned a malformed response"
            ) from exc
        return LLMResult(
            content=content,
            provider=self.provider_name,
            model=self.model,
            duration_ms=duration,
            usage=LLMUsage(
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
            ),
        )

    def invoke(self, messages: list[LLMMessage], *, max_output_tokens: int = 512) -> LLMResult:
        return self._call(messages, None, None, max_output_tokens)

    def invoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]:
        result = self._call(
            messages,
            output_type.__name__.lower(),
            output_type.model_json_schema(),
            max_output_tokens,
        )
        return _validate(result.content, output_type, self.provider_name), result


class OllamaProvider(AsyncProviderMixin):
    provider_name = "ollama"

    def __init__(
        self,
        model: str,
        timeout: float,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=timeout)

    def _call(
        self,
        messages: list[LLMMessage],
        schema: dict[str, Any] | None,
        max_output_tokens: int,
    ) -> LLMResult:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [item.__dict__ for item in messages],
            "stream": False,
            "options": {"temperature": 0, "num_predict": max_output_tokens},
        }
        if schema is not None:
            body["format"] = schema
        started = time.perf_counter()
        try:
            response = self.client.post(f"{self.base_url}/api/chat", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _raise_http_error(self.provider_name, self.model, exc)
        duration = round((time.perf_counter() - started) * 1000)
        try:
            payload = response.json()
            content = payload["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise LLMMalformedResponseError("Ollama returned a malformed response") from exc
        return LLMResult(content, self.provider_name, self.model, duration)

    def invoke(self, messages: list[LLMMessage], *, max_output_tokens: int = 512) -> LLMResult:
        return self._call(messages, None, max_output_tokens)

    def invoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]:
        result = self._call(messages, output_type.model_json_schema(), max_output_tokens)
        return _validate(result.content, output_type, self.provider_name), result
