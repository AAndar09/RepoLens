import asyncio

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.llm.base import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMMalformedResponseError,
    LLMMessage,
    LLMProviderError,
    LLMRateLimitError,
    LLMResult,
    LLMUnavailableError,
)
from app.llm.factory import FallbackLLMProvider, create_configured_provider, create_provider
from app.llm.providers import GeminiProvider, OllamaProvider, OpenAICompatibleProvider


class SampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


MESSAGES = [LLMMessage("system", "Be concise"), LLMMessage("user", "Answer")]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=1)


def test_gemini_structured_success_and_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-key"
        assert request.url.path.endswith("/models/gemini-test:generateContent")
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"answer":"yes"}'}]}}],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 5,
                },
            },
        )

    provider = GeminiProvider("gemini-test", "test-key", 1, "https://gemini.test", _client(handler))
    value, result = provider.invoke_structured(MESSAGES, SampleOutput)

    assert value.answer == "yes"
    assert result.provider == "gemini"
    assert result.usage.total_tokens == 5


@pytest.mark.parametrize("name", ["groq", "openrouter"])
def test_openai_compatible_structured_success(name: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        expected_format = "json_object" if name == "groq" else "json_schema"
        assert f'"type":"{expected_format}"' in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"answer":"yes"}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            },
        )

    provider = OpenAICompatibleProvider(
        name, "model-test", "test-key", 1, f"https://{name}.test/v1", _client(handler)
    )
    value, result = provider.invoke_structured(MESSAGES, SampleOutput)

    assert value.answer == "yes"
    assert result.provider == name
    assert result.usage.total_tokens == 6


def test_ollama_remains_selectable_and_structured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, json={"message": {"content": '{"answer":"local"}'}})

    provider = OllamaProvider("local-test", 1, "http://ollama.test", _client(handler))
    value, result = provider.invoke_structured(MESSAGES, SampleOutput)

    assert value.answer == "local"
    assert result.provider == "ollama"


def test_provider_supports_async_structured_invocation() -> None:
    provider = OllamaProvider(
        "local-test",
        1,
        "http://ollama.test",
        _client(
            lambda request: httpx.Response(
                200, json={"message": {"content": '{"answer":"async"}'}}, request=request
            )
        ),
    )
    value, _ = asyncio.run(provider.ainvoke_structured(MESSAGES, SampleOutput))
    assert value.answer == "async"


def test_timeout_rate_limit_and_malformed_response_are_typed() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    timeout_provider = GeminiProvider(
        "gemini-test", "key", 1, "https://gemini.test", _client(timeout_handler)
    )
    with pytest.raises(LLMUnavailableError):
        timeout_provider.invoke(MESSAGES)

    rate_provider = OpenAICompatibleProvider(
        "groq",
        "model-test",
        "key",
        1,
        "https://groq.test/v1",
        _client(lambda request: httpx.Response(429, request=request)),
    )
    with pytest.raises(LLMRateLimitError):
        rate_provider.invoke(MESSAGES)

    malformed_provider = GeminiProvider(
        "gemini-test",
        "key",
        1,
        "https://gemini.test",
        _client(lambda request: httpx.Response(200, json={"candidates": []}, request=request)),
    )
    with pytest.raises(LLMMalformedResponseError):
        malformed_provider.invoke(MESSAGES)

    rejected_provider = OpenAICompatibleProvider(
        "groq",
        "model-test",
        "key",
        1,
        "https://groq.test/v1",
        _client(lambda request: httpx.Response(400, request=request)),
    )
    with pytest.raises(LLMProviderError, match="status 400"):
        rejected_provider.invoke(MESSAGES)

    detailed_rejection = OpenAICompatibleProvider(
        "groq",
        "model-test",
        "key",
        1,
        "https://groq.test/v1",
        _client(
            lambda request: httpx.Response(
                400,
                json={"error": {"message": "response_format is unsupported"}},
                request=request,
            )
        ),
    )
    with pytest.raises(LLMProviderError, match="response_format is unsupported"):
        detailed_rejection.invoke(MESSAGES)

    auth_provider = GeminiProvider(
        "gemini-test",
        "bad-key",
        1,
        "https://gemini.test",
        _client(lambda request: httpx.Response(401, request=request)),
    )
    with pytest.raises(LLMAuthenticationError):
        auth_provider.invoke(MESSAGES)


class FakeProvider:
    def __init__(self, name: str, outcome) -> None:
        self.provider_name = name
        self.model = f"{name}-model"
        self.outcome = outcome
        self.calls = 0

    def invoke_structured(self, messages, output_type, *, max_output_tokens=512):
        del messages, output_type, max_output_tokens
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return SampleOutput(answer=self.outcome), LLMResult(
            '{"answer":"yes"}', self.provider_name, self.model, 1
        )

    def invoke(self, messages, *, max_output_tokens=512):
        del messages, max_output_tokens
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return LLMResult(self.outcome, self.provider_name, self.model, 1)


def test_fallback_is_bounded_and_only_used_for_retryable_failure() -> None:
    primary = FakeProvider("primary", LLMUnavailableError("offline"))
    fallback = FakeProvider("fallback", "fallback answer")
    provider = FallbackLLMProvider(primary, fallback)

    value, result = provider.invoke_structured(MESSAGES, SampleOutput)

    assert value.answer == "fallback answer"
    assert result.fallback_used is True
    assert primary.calls == fallback.calls == 1
    assert [run.success for run in provider.runs] == [False, True]


def test_primary_success_skips_fallback_and_double_failure_is_controlled() -> None:
    primary = FakeProvider("primary", "primary answer")
    fallback = FakeProvider("fallback", "unused")
    provider = FallbackLLMProvider(primary, fallback)
    provider.invoke_structured(MESSAGES, SampleOutput)
    assert fallback.calls == 0

    both_fail = FallbackLLMProvider(
        FakeProvider("primary", LLMUnavailableError("offline")),
        FakeProvider("fallback", LLMUnavailableError("also offline")),
    )
    with pytest.raises(LLMUnavailableError, match="also offline"):
        both_fail.invoke_structured(MESSAGES, SampleOutput)

    non_retryable_fallback = FakeProvider("fallback", "must not run")
    non_retryable = FallbackLLMProvider(
        FakeProvider("primary", LLMMalformedResponseError("bad JSON")),
        non_retryable_fallback,
    )
    with pytest.raises(LLMMalformedResponseError):
        non_retryable.invoke_structured(MESSAGES, SampleOutput)
    assert non_retryable_fallback.calls == 0


def test_factory_selection_models_and_lazy_credentials() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_model="gemini-custom",
        llm_fallback_provider="groq",
        llm_fallback_model="groq-custom",
    )
    configured = create_configured_provider(settings)
    assert configured.primary.provider_name == "gemini"
    assert configured.primary.model == "gemini-custom"
    assert configured.fallback is not None
    assert configured.fallback.model == "groq-custom"

    ollama = create_provider(settings, "ollama", "qwen-local")
    assert ollama.provider_name == "ollama"
    with pytest.raises(LLMConfigurationError, match="Unsupported LLM provider"):
        create_provider(settings, "unknown", "model")
