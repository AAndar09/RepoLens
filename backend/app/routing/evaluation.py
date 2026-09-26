from dataclasses import dataclass

from app.routing.service import QueryCategory, QueryClassifier, RouteStrategy


@dataclass(frozen=True)
class RoutingExample:
    question: str
    category: QueryCategory
    strategy: RouteStrategy


ROUTING_EVALUATION_DATASET: tuple[RoutingExample, ...] = (
    RoutingExample(
        "What commit was indexed?",
        QueryCategory.REPOSITORY_METADATA,
        RouteStrategy.REPOSITORY_METADATA,
    ),
    RoutingExample(
        "Where is `RepositoryIngestor` defined?",
        QueryCategory.SYMBOL_LOOKUP,
        RouteStrategy.DIRECT_SYMBOL_LOOKUP,
    ),
    RoutingExample(
        "How do the API and persistence layers fit together?",
        QueryCategory.ARCHITECTURE,
        RouteStrategy.HYBRID_RETRIEVAL,
    ),
    RoutingExample(
        "How is the clone timeout enforced?",
        QueryCategory.IMPLEMENTATION,
        RouteStrategy.HYBRID_RETRIEVAL,
    ),
    RoutingExample(
        "Which modules import the graph service?",
        QueryCategory.DEPENDENCY,
        RouteStrategy.FULL_INVESTIGATION,
    ),
    RoutingExample(
        "What security risks exist in repository URL validation?",
        QueryCategory.SECURITY,
        RouteStrategy.FULL_INVESTIGATION,
    ),
    RoutingExample(
        "How is this project configured locally?",
        QueryCategory.DOCUMENTATION,
        RouteStrategy.HYBRID_RETRIEVAL,
    ),
)


def evaluate_classifier(classifier: QueryClassifier) -> dict[str, object]:
    category_correct = 0
    strategy_correct = 0
    rows: list[dict[str, object]] = []
    for example in ROUTING_EVALUATION_DATASET:
        actual = classifier.classify(example.question)
        category_match = actual.category is example.category
        strategy_match = actual.strategy is example.strategy
        category_correct += category_match
        strategy_correct += strategy_match
        rows.append(
            {
                "question": example.question,
                "expected_category": example.category,
                "actual_category": actual.category,
                "expected_strategy": example.strategy,
                "actual_strategy": actual.strategy,
                "category_correct": category_match,
                "strategy_correct": strategy_match,
            }
        )
    total = len(ROUTING_EVALUATION_DATASET)
    return {
        "total": total,
        "category_accuracy": category_correct / total,
        "strategy_accuracy": strategy_correct / total,
        "rows": rows,
    }
