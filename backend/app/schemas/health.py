from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    vector_database: Literal["ok"] | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"]
