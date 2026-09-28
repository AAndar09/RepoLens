import logging
import re
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

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
    router: str = "rules"


class QueryClassifier(Protocol):
    def classify(self, question: str) -> RoutingDecision: ...


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


_CATEGORY_PATTERNS: tuple[tuple[QueryCategory, tuple[str, ...]], ...] = (
    (
        QueryCategory.SECURITY,
        (
            r"\bsecurity\b",
            r"\bvulnerab(?:ility|ilities|le)\b",
            r"\bcve(?:s)?\b",
            r"\bexploit(?:able|ability)?\b",
            r"\bunsafe\b",
        ),
    ),
    (
        QueryCategory.DEPENDENCY,
        (
            r"\bdependenc(?:y|ies)\b",
            r"\bimports?\b",
            r"\bimporters?\b",
            r"\bpackages?\b",
            r"\brequirements(?:\.txt)?\b",
            r"\bpyproject(?:\.toml)?\b",
        ),
    ),
    (
        QueryCategory.REPOSITORY_METADATA,
        (
            r"\bcommit(?: sha)?\b",
            r"\bbranch\b",
            r"\bsnapshot\b",
            r"\bindexed (?:commit|branch|snapshot)\b",
            r"\brepository (?:name|owner|url|metadata)\b",
        ),
    ),
    (
        QueryCategory.DOCUMENTATION,
        (
            r"\breadme\b",
            r"\bdocs?\b",
            r"\bdocumentation\b",
            r"\bsetup\b",
            r"\binstall(?:ation|ed|ing)?\b",
            r"\bconfigur(?:e|ed|ation|ing)\b",
            r"\bhow (?:do|can|should) (?:i|we) (?:use|run|start)\b",
        ),
    ),
    (
        QueryCategory.ARCHITECTURE,
        (
            r"\barchitecture\b",
            r"\bcomponents?\b",
            r"\blayers?\b",
            r"\bfit together\b",
            r"\bcodebase structure\b",
            r"\bdata flow\b",
        ),
    ),
    (
        QueryCategory.IMPLEMENTATION,
        (
            r"\bimplement(?:ed|ation|ing|s)?\b",
            r"\benforc(?:e|ed|ement|ing)\b",
            r"\bvalidat(?:e|ed|es|ion|ing)\b",
            r"\bwhat happens when\b",
        ),
    ),
)

_SYMBOL_LOOKUP = re.compile(
    r"(?i:\b(?:where is|find|locate|defined|definition of)\b).*"
    r"(?:`[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*`|"
    r"'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*'|"
    r"\b[A-Z][A-Za-z0-9_]*\b)"
)


class RuleBasedQueryClassifier:
    """Classify obvious query shapes without loading or calling an AI model."""

    def classify(self, question: str) -> RoutingDecision:
        normalized = " ".join(question.strip().split())
        lowered = normalized.lower()

        if _SYMBOL_LOOKUP.search(normalized):
            decision = self._decision(
                QueryCategory.SYMBOL_LOOKUP,
                0.95,
                "Question explicitly requests a named code symbol",
            )
        else:
            matches = [
                category
                for category, patterns in _CATEGORY_PATTERNS
                if any(re.search(pattern, lowered) for pattern in patterns)
            ]
            if len(matches) == 1:
                decision = self._decision(
                    matches[0],
                    0.90,
                    f"Matched deterministic {matches[0].value} query signals",
                )
            elif matches:
                decision = RoutingDecision(
                    category=matches[0],
                    confidence=0.50,
                    strategy=RouteStrategy.FULL_INVESTIGATION,
                    rationale=(
                        "Question matched multiple categories; using the general investigation path"
                    ),
                    fallback_applied=True,
                )
            else:
                decision = RoutingDecision(
                    category=QueryCategory.UNKNOWN,
                    confidence=0,
                    strategy=RouteStrategy.FULL_INVESTIGATION,
                    rationale=(
                        "No deterministic route matched; using the general investigation path"
                    ),
                    fallback_applied=True,
                )

        logger.info(
            "routing_decision",
            extra={
                "event": "routing_decision",
                "router": decision.router,
                "category": decision.category,
                "strategy": decision.strategy,
                "confidence": decision.confidence,
                "fallback": decision.fallback_applied,
            },
        )
        return decision

    @staticmethod
    def _decision(
        category: QueryCategory, confidence: float, rationale: str
    ) -> RoutingDecision:
        return RoutingDecision(
            category=category,
            confidence=confidence,
            strategy=strategy_for(category),
            rationale=rationale,
        )
