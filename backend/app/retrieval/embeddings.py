import hashlib
import math
import re
from typing import Protocol

from app.config import Settings

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
CAMEL_CASE_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


class EmbeddingConfigurationError(ValueError):
    pass


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def lexical_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in TOKEN_PATTERN.findall(text):
        normalized = CAMEL_CASE_BOUNDARY.sub(r"\1 \2", token).replace("_", " ").lower()
        tokens.extend(part for part in normalized.split() if part)
    return tokens


class HashingEmbeddingProvider:
    """A deterministic local dense embedding suitable for offline development and tests."""

    name = "hashing"

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    @staticmethod
    def _feature_hash(feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        integer = int.from_bytes(digest, "big")
        return integer, -1.0 if integer & 1 else 1.0

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in lexical_tokens(text):
            integer, sign = self._feature_hash(f"word:{token}")
            vector[integer % self.dimensions] += sign
            if len(token) >= 4:
                for index in range(len(token) - 2):
                    integer, sign = self._feature_hash(f"trigram:{token[index:index + 3]}")
                    vector[integer % self.dimensions] += sign * 0.25
        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            return [value / magnitude for value in vector]
        return vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == HashingEmbeddingProvider.name:
        return HashingEmbeddingProvider(settings.embedding_dimensions)
    raise EmbeddingConfigurationError(
        f"Unsupported embedding provider: {settings.embedding_provider}. "
        "Configure REPOLENS_EMBEDDING_PROVIDER=hashing."
    )

