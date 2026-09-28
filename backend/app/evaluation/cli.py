import argparse
import sys
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_engine
from app.evaluation.dataset import load_dataset
from app.evaluation.runner import EvaluationError, EvaluationRunner
from app.retrieval.embeddings import create_embedding_provider
from app.retrieval.vector_store import QdrantVectorStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic RepoLens benchmarks against indexed immutable snapshots."
    )
    parser.add_argument("dataset", type=Path, help="Path to a versioned evaluation dataset JSON")
    parser.add_argument(
        "--configuration",
        action="append",
        choices=("lexical", "semantic", "hybrid"),
        dest="configurations",
        help="Retrieval configuration to benchmark; repeat to compare (default: semantic, hybrid)",
    )
    parser.add_argument(
        "-k",
        action="append",
        type=int,
        dest="k_values",
        help="Recall/citation cutoff; repeat for multiple values (default: 1, 3, 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report to this path instead of stdout",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        dataset, dataset_hash = load_dataset(arguments.dataset)
        settings = get_settings()
        embedding_provider = create_embedding_provider(settings)
        with Session(get_engine(), expire_on_commit=False) as session:
            report = EvaluationRunner(
                session,
                settings,
                QdrantVectorStore(settings),
                embedding_provider,
            ).run(
                dataset,
                dataset_hash,
                configurations=tuple(arguments.configurations or ("semantic", "hybrid")),
                k_values=tuple(arguments.k_values or (1, 3, 5)),
            )
    except (OSError, ValueError, ValidationError, EvaluationError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2

    serialized = report.model_dump_json(indent=2)
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote evaluation report to {arguments.output}")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
