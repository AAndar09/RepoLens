import logging
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings

logger = logging.getLogger(__name__)


class QueryCategory(StrEnum):
    ARCHITECTURE = "architecture"
    IMPLEMENTATION = "implementation"
    SYMBOL_LOOKUP = "symbol_lookup"
    DEPENDENCY = "dependency"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    REPOSITORY_METADATA = "repository_metadata"
    UNKNOWN = "unknown"


class RouteStrategy(StrEnum):
    REPOSITORY_METADATA = "repository_metadata"
    DIRECT_SYMBOL_LOOKUP = "direct_symbol_lookup"
    HYBRID_RETRIEVAL = "hybrid_retrieval"
    FULL_INVESTIGATION = "full_investigation"


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: QueryCategory
    confidence: float = Field(ge=0, le=1)
    strategy: RouteStrategy
    rationale: str
    fallback_applied: bool = False
    router: str = "laya"


class QueryClassifier(Protocol):
    def classify(self, question: str) -> RoutingDecision: ...


_CATEGORY_CRITERIA = {
    QueryCategory.ARCHITECTURE.value: "System structure, components, and how parts relate.",
    QueryCategory.IMPLEMENTATION.value: "How code implements a behaviour or algorithm.",
    QueryCategory.SYMBOL_LOOKUP.value: (
        "Find or identify a named class, function, method, or module."
    ),
    QueryCategory.DEPENDENCY.value: "Imports, dependencies, importers, or module relationships.",
    QueryCategory.DOCUMENTATION.value: (
        "Repository documentation, usage, setup, or public interfaces."
    ),
    QueryCategory.SECURITY.value: "Potential security properties or risks in indexed source code.",
    QueryCategory.REPOSITORY_METADATA.value: (
        "Snapshot identity, branch, commit, or indexed counts."
    ),
    QueryCategory.UNKNOWN.value: "Does not clearly match another category.",
}


def strategy_for(category: QueryCategory) -> RouteStrategy:
    if category is QueryCategory.REPOSITORY_METADATA:
        return RouteStrategy.REPOSITORY_METADATA
    if category is QueryCategory.SYMBOL_LOOKUP:
        return RouteStrategy.DIRECT_SYMBOL_LOOKUP
    if category in {
        QueryCategory.ARCHITECTURE,
        QueryCategory.IMPLEMENTATION,
        QueryCategory.DOCUMENTATION,
    }:
        return RouteStrategy.HYBRID_RETRIEVAL
    return RouteStrategy.FULL_INVESTIGATION


class LayaQueryClassifier:
    """A lazy adapter so loading Laya's local model never blocks application startup."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._router: Any | None = None

    def _get_router(self) -> Any:
        if self._router is None:
            try:
                from laya import Router
            except ImportError as exc:  # pragma: no cover - packaging failure guard
                raise RuntimeError("Laya is not installed in the backend environment") from exc
            self._router = Router()
        return self._router

    def classify(self, question: str) -> RoutingDecision:
        try:
            response = self._get_router().predict(
                {"question": question},
                {
                    "category": {
                        "type": "choice",
                        "instructions": (
                            "Classify the repository question into exactly one category."
                        ),
                        "criteria": _CATEGORY_CRITERIA,
                    }
                },
                model=self.settings.routing_laya_model,
            )
            category, confidence = self._parse_response(response)
            decision = RoutingDecision(
                category=category,
                confidence=confidence,
                strategy=strategy_for(category),
                rationale="Laya typed-decision classification",
            )
        except Exception as exc:
            logger.warning("laya_routing_failed error=%s", exc)
            decision = RoutingDecision(
                category=QueryCategory.UNKNOWN,
                confidence=0,
                strategy=RouteStrategy.FULL_INVESTIGATION,
                rationale="Laya was unavailable or returned an unrecognised decision",
                fallback_applied=True,
            )
        decision = self._apply_confidence_fallback(decision)
        logger.info(
            "routing_decision category=%s strategy=%s confidence=%.2f fallback=%s",
            decision.category,
            decision.strategy,
            decision.confidence,
            decision.fallback_applied,
        )
        return decision

    @staticmethod
    def _parse_response(response: Any) -> tuple[QueryCategory, float]:
        """Accept Laya's documented routing envelopes without trusting untyped data."""
        if hasattr(response, "model_dump"):
            response = response.model_dump()
        if not isinstance(response, dict):
            raise ValueError("Laya response was not an object")
        payload = response.get("category", response.get("routing", response))
        if not isinstance(payload, dict):
            raise ValueError("Laya category payload was not an object")
        raw_category = payload.get("category") or payload.get("choice")
        if isinstance(raw_category, dict):
            raw_category = raw_category.get("value") or raw_category.get("choice")
        category = QueryCategory(str(raw_category))
        probabilities = payload.get("probabilities", {})
        raw_confidence = payload.get("confidence")
        if raw_confidence is None and isinstance(probabilities, dict):
            raw_confidence = probabilities.get(raw_category)
        if raw_confidence is None:
            raw_confidence = response.get("confidence", 0.0)
        confidence = float(raw_confidence)
        if not 0 <= confidence <= 1:
            raise ValueError("Laya confidence was outside [0, 1]")
        return category, confidence

    def _apply_confidence_fallback(self, decision: RoutingDecision) -> RoutingDecision:
        if decision.confidence >= self.settings.routing_confidence_threshold:
            return decision
        return decision.model_copy(
            update={
                "strategy": RouteStrategy.FULL_INVESTIGATION,
                "fallback_applied": True,
                "rationale": (
                    f"{decision.rationale}; confidence {decision.confidence:.2f} is below "
                    f"the configured {self.settings.routing_confidence_threshold:.2f} threshold"
                ),
            }
        )
