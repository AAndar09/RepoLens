import asyncio
from dataclasses import dataclass, replace
from typing import Protocol, TypeVar

from pydantic import BaseModel

OutputModel = TypeVar("OutputModel", bound=BaseModel)


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class LLMResult:
    content: str
    provider: str
    model: str
    duration_ms: int
    usage: LLMUsage = LLMUsage()
    fallback_used: bool = False


@dataclass(frozen=True)
class LLMRun:
    operation: str
    provider: str
    model: str
    duration_ms: int
    success: bool
    fallback_used: bool
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    error_type: str | None = None


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMConfigurationError(LLMProviderError):
    pass


class LLMAuthenticationError(LLMProviderError):
    pass


class LLMUnavailableError(LLMProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class LLMRateLimitError(LLMUnavailableError):
    pass


class LLMMalformedResponseError(LLMProviderError):
    pass


class LLMProvider(Protocol):
    provider_name: str
    model: str

    def invoke(self, messages: list[LLMMessage], *, max_output_tokens: int = 512) -> LLMResult: ...

    def invoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]: ...

    async def ainvoke(
        self, messages: list[LLMMessage], *, max_output_tokens: int = 512
    ) -> LLMResult: ...

    async def ainvoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]: ...


class AsyncProviderMixin:
    async def ainvoke(
        self, messages: list[LLMMessage], *, max_output_tokens: int = 512
    ) -> LLMResult:
        return await asyncio.to_thread(
            self.invoke,
            messages,
            max_output_tokens=max_output_tokens,  # type: ignore[attr-defined]
        )

    async def ainvoke_structured(
        self,
        messages: list[LLMMessage],
        output_type: type[OutputModel],
        *,
        max_output_tokens: int = 512,
    ) -> tuple[OutputModel, LLMResult]:
        return await asyncio.to_thread(
            self.invoke_structured,  # type: ignore[attr-defined]
            messages,
            output_type,
            max_output_tokens=max_output_tokens,
        )


def result_run(result: LLMResult, operation: str) -> LLMRun:
    return LLMRun(
        operation=operation,
        provider=result.provider,
        model=result.model,
        duration_ms=result.duration_ms,
        success=True,
        fallback_used=result.fallback_used,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        total_tokens=result.usage.total_tokens,
    )


def mark_fallback(result: LLMResult) -> LLMResult:
    return replace(result, fallback_used=True)
