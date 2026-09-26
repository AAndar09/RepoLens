from app.config import Settings
from app.routing.evaluation import evaluate_classifier
from app.routing.service import LayaQueryClassifier, QueryCategory, RouteStrategy, RoutingDecision


class FakeLayaRouter:
    def __init__(self, category: str, confidence: float) -> None:
        self.category = category
        self.confidence = confidence

    def predict(self, state, questions, model):
        assert state["question"]
        assert "category" in questions
        assert model == "typed-decisions"
        return {
            "category": {
                "choice": self.category,
                "probabilities": {self.category: self.confidence},
            },
            "routing": {"model": "typed-decisions"},
        }


def test_laya_category_selects_a_narrow_route() -> None:
    classifier = LayaQueryClassifier(Settings(_env_file=None))
    classifier._router = FakeLayaRouter("repository_metadata", 0.91)
    decision = classifier.classify("Which commit was indexed?")
    assert decision.category is QueryCategory.REPOSITORY_METADATA
    assert decision.strategy is RouteStrategy.REPOSITORY_METADATA
    assert not decision.fallback_applied


def test_low_confidence_laya_result_falls_back_to_investigation() -> None:
    classifier = LayaQueryClassifier(Settings(_env_file=None, routing_confidence_threshold=0.7))
    classifier._router = FakeLayaRouter("implementation", 0.4)
    decision = classifier.classify("How is ingestion implemented?")
    assert decision.category is QueryCategory.IMPLEMENTATION
    assert decision.strategy is RouteStrategy.FULL_INVESTIGATION
    assert decision.fallback_applied


class PerfectClassifier:
    def classify(self, question: str) -> RoutingDecision:
        from app.routing.evaluation import ROUTING_EVALUATION_DATASET

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
