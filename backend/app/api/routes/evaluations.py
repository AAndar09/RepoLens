import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.evaluation.report import EvaluationReport
from app.schemas.evaluation import EvaluationResultSummary

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
logger = logging.getLogger(__name__)


def _read_reports(settings: Settings) -> list[EvaluationReport]:
    directory = Path(settings.evaluation_results_dir)
    if not directory.is_dir():
        return []
    reports: list[EvaluationReport] = []
    for path in sorted(directory.glob("*.json"))[: settings.evaluation_max_results]:
        try:
            if path.stat().st_size > settings.evaluation_max_result_bytes:
                raise ValueError("result exceeds configured size limit")
            report = EvaluationReport.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "evaluation_result_skipped",
                extra={
                    "event": "evaluation_result_skipped",
                    "result_file": path.name,
                    "error_type": exc.__class__.__name__,
                },
            )
            continue
        reports.append(report)
    return sorted(reports, key=lambda item: item.generated_at, reverse=True)


@router.get("/results", response_model=list[EvaluationResultSummary])
def list_evaluation_results(
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[EvaluationResultSummary]:
    return [
        EvaluationResultSummary.model_validate(report, from_attributes=True)
        for report in _read_reports(settings)
    ]
