from app.routing.evaluation import ROUTING_EVALUATION_DATASET, evaluate_classifier
from app.routing.service import (
    QueryCategory,
    RouteStrategy,
    RoutingDecision,
    RuleBasedQueryClassifier,
)


def test_rule_based_classifier_selects_metadata_route() -> None:
    decision = RuleBasedQueryClassifier().classify("Which commit was indexed?")

    assert decision.category is QueryCategory.REPOSITORY_METADATA
    assert decision.strategy is RouteStrategy.REPOSITORY_METADATA
    assert decision.router == "rules"
    assert not decision.fallback_applied


def test_rule_based_classifier_selects_named_symbol_route() -> None:
    decision = RuleBasedQueryClassifier().classify("Where is `RepositoryIngestor` defined?")

    assert decision.category is QueryCategory.SYMBOL_LOOKUP
    assert decision.strategy is RouteStrategy.DIRECT_SYMBOL_LOOKUP
    assert not decision.fallback_applied


def test_unknown_question_falls_back_to_investigation() -> None:
    decision = RuleBasedQueryClassifier().classify("Tell me something useful about this code")

    assert decision.category is QueryCategory.UNKNOWN
    assert decision.strategy is RouteStrategy.FULL_INVESTIGATION
    assert decision.fallback_applied


def test_ambiguous_question_falls_back_to_investigation() -> None:
    decision = RuleBasedQueryClassifier().classify(
        "How is dependency input validated for security?"
    )

    assert decision.strategy is RouteStrategy.FULL_INVESTIGATION
    assert decision.fallback_applied


class PerfectClassifier:
    def classify(self, question: str) -> RoutingDecision:
        example = next(item for item in ROUTING_EVALUATION_DATASET if item.question == question)
        return RoutingDecision(
            category=example.category,
            confidence=1,
            strategy=example.strategy,
            rationale="test fixture",
        )


def test_routing_evaluation_reports_measured_accuracy() -> None:
    result = evaluate_classifier(PerfectClassifier())
    assert result["total"] == 7
    assert result["category_accuracy"] == 1
    assert result["strategy_accuracy"] == 1


def test_rule_based_classifier_matches_labelled_evaluation_dataset() -> None:
    result = evaluate_classifier(RuleBasedQueryClassifier())

    assert result["category_accuracy"] == 1
    assert result["strategy_accuracy"] == 1
