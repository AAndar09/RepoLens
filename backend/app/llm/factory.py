import logging
import time

from app.config import Settings
from app.llm.base import (
    LLMConfigurationError,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResult,
    LLMRun,
    OutputModel,
    mark_fallback,
    result_run,
)
from app.llm.providers import GeminiProvider, OllamaProvider, OpenAICompatibleProvider

logger = logging.getLogger(__name__)


def _secret(value) -> str | None:
    return value.get_secret_value() if value is not None else None


def create_provider(settings: Settings, provider_name: str, model: str) -> LLMProvider:
    name = provider_name.strip().lower()
    if not model.strip():
        raise LLMConfigurationError(f"No model configured for provider {name}")
    if name == "gemini":
        return GeminiProvider(
            model,
            _secret(settings.gemini_api_key),
            settings.llm_timeout_seconds,
            settings.gemini_base_url,
        )
    if name == "groq":
        return OpenAICompatibleProvider(
            name,
            model,
            _secret(settings.groq_api_key),
            settings.llm_timeout_seconds,
            settings.groq_base_url,
        )
    if name == "openrouter":
        headers = {"X-Title": "RepoLens"}
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        return OpenAICompatibleProvider(
            name,
            model,
            _secret(settings.openrouter_api_key),
            settings.llm_timeout_seconds,
            settings.openrouter_base_url,
            extra_headers=headers,
        )
    if name == "ollama":
        return OllamaProvider(model, settings.llm_timeout_seconds, settings.ollama_url)
    raise LLMConfigurationError(
        f"Unsupported LLM provider '{provider_name}'. Expected gemini, groq, openrouter, or ollama"
    )


class FallbackLLMProvider:
    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None) -> None:
        self.primary = primary
        self.fallback = fallback
        self.provider_name = primary.provider_name
        self.model = primary.model
        self.runs: list[LLMRun] = []

    def _failure(
        self,
        provider: LLMProvider,
        operation: str,
        exc: LLMProviderError,
        fallback: bool,
        duration_ms: int,
    ):
        self.runs.append(
            LLMRun(
                operation,
                provider.provider_name,
                provider.model,
                duration_ms,
                False,
                fallback,
                error_type=exc.__class__.__name__,
            )
        )
        logger.warning(
            "llm_call provider=%s model=%s operation=%s success=false fallback=%s error=%s",
            provider.provider_name,
            provider.model,
            operation,
            fallback,
            exc.__class__.__name__,
        )

    def _success(self, result: LLMResult, operation: str) -> LLMResult:
        self.runs.append(result_run(result, operation))
        logger.info(
            "llm_call provider=%s model=%s operation=%s duration_ms=%s success=true "
            "fallback=%s input_tokens=%s output_tokens=%s",
            result.provider,
            result.model,
            operation,
            result.duration_ms,
            result.fallback_used,
            result.usage.input_tokens,
            result.usage.output_tokens,
        )
        return result

    def invoke(self, messages: list[LLMMessage], *, max_output_tokens: int = 512) -> LLMResult:
        operation = "chat"
        started = time.perf_counter()
        try:
            return self._success(
                self.primary.invoke(messages, max_output_tokens=max_output_tokens), operation
            )
        except LLMProviderError as exc:
            self._failure(
                self.primary,
                operation,
                exc,
                False,
                round((time.perf_counter() - started) * 1000),
            )
            if not exc.retryable or self.fallback is None:
                raise
        started = time.perf_counter()
        try:
            result = mark_fallback(
                self.fallback.invoke(messages, max_output_tokens=max_output_tokens)
            )
            return self._success(result, operation)
        except LLMProviderError as exc:
            self._failure(
                self.fallback,
                operation,
                exc,
                True,
                round((time.perf_counter() - started) * 1000),
            )
            raise

    def invoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]:
        operation = output_type.__name__
        started = time.perf_counter()
        try:
            value, result = self.primary.invoke_structured(
                messages, output_type, max_output_tokens=max_output_tokens
            )
            return value, self._success(result, operation)
        except LLMProviderError as exc:
            self._failure(
                self.primary,
                operation,
                exc,
                False,
                round((time.perf_counter() - started) * 1000),
            )
            if not exc.retryable or self.fallback is None:
                raise
        started = time.perf_counter()
        try:
            value, result = self.fallback.invoke_structured(
                messages, output_type, max_output_tokens=max_output_tokens
            )
            return value, self._success(mark_fallback(result), operation)
        except LLMProviderError as exc:
            self._failure(
                self.fallback,
                operation,
                exc,
                True,
                round((time.perf_counter() - started) * 1000),
            )
            raise

    async def ainvoke(
        self, messages: list[LLMMessage], *, max_output_tokens: int = 512
    ) -> LLMResult:
        import asyncio

        return await asyncio.to_thread(self.invoke, messages, max_output_tokens=max_output_tokens)

    async def ainvoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]:
        import asyncio

        return await asyncio.to_thread(
            self.invoke_structured, messages, output_type, max_output_tokens=max_output_tokens
        )


def create_configured_provider(settings: Settings) -> FallbackLLMProvider:
    primary = create_provider(settings, settings.llm_provider, settings.llm_model)
    fallback_name = settings.llm_fallback_provider.strip()
    fallback_model = settings.llm_fallback_model.strip()
    fallback = (
        create_provider(settings, fallback_name, fallback_model)
        if fallback_name and fallback_model
        else None
    )
    return FallbackLLMProvider(primary, fallback)
