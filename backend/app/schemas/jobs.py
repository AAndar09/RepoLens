import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.ingestion_job import IngestionJobStatus


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    snapshot_id: uuid.UUID | None
    status: IngestionJobStatus
    attempt_count: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
