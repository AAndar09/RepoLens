import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config import Settings


class VectorStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class VectorPoint:
    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any]


@dataclass(frozen=True)
class VectorHit:
    id: uuid.UUID
    score: float


class VectorStore(Protocol):
    def ensure_collection(self, collection_name: str, dimensions: int) -> None: ...

    def replace_snapshot(
        self, collection_name: str, snapshot_id: uuid.UUID, points: list[VectorPoint]
    ) -> None: ...

    def search(
        self,
        collection_name: str,
        vector: list[float],
        snapshot_id: uuid.UUID,
        limit: int,
        filepath: str | None = None,
        symbol_kind: str | None = None,
        language: str | None = None,
    ) -> list[VectorHit]: ...


class QdrantVectorStore:
    def __init__(self, settings: Settings) -> None:
        self.client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    @staticmethod
    def _snapshot_filter(
        snapshot_id: uuid.UUID,
        *,
        filepath: str | None = None,
        symbol_kind: str | None = None,
        language: str | None = None,
    ) -> models.Filter:
        conditions: list[models.FieldCondition] = [
            models.FieldCondition(
                key="snapshot_id",
                match=models.MatchValue(value=str(snapshot_id)),
            )
        ]
        for key, value in (
            ("filepath", filepath),
            ("symbol_kind", symbol_kind),
            ("language", language),
        ):
            if value is not None:
                conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=value))
                )
        return models.Filter(must=conditions)

    def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        try:
            if not self.client.collection_exists(collection_name):
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=dimensions,
                        distance=models.Distance.COSINE,
                    ),
                )
        except (UnexpectedResponse, OSError) as exc:
            raise VectorStoreError("Unable to prepare the Qdrant collection") from exc

    def replace_snapshot(
        self, collection_name: str, snapshot_id: uuid.UUID, points: list[VectorPoint]
    ) -> None:
        try:
            self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(filter=self._snapshot_filter(snapshot_id)),
                wait=True,
            )
            for start in range(0, len(points), 64):
                batch = points[start : start + 64]
                self.client.upsert(
                    collection_name=collection_name,
                    points=[
                        models.PointStruct(
                            id=str(point.id), vector=point.vector, payload=point.payload
                        )
                        for point in batch
                    ],
                    wait=True,
                )
        except (UnexpectedResponse, OSError) as exc:
            raise VectorStoreError("Unable to write vectors to Qdrant") from exc

    def search(
        self,
        collection_name: str,
        vector: list[float],
        snapshot_id: uuid.UUID,
        limit: int,
        filepath: str | None = None,
        symbol_kind: str | None = None,
        language: str | None = None,
    ) -> list[VectorHit]:
        try:
            response = self.client.query_points(
                collection_name=collection_name,
                query=vector,
                query_filter=self._snapshot_filter(
                    snapshot_id,
                    filepath=filepath,
                    symbol_kind=symbol_kind,
                    language=language,
                ),
                limit=limit,
                with_payload=False,
                with_vectors=False,
            )
        except (UnexpectedResponse, OSError) as exc:
            raise VectorStoreError("Unable to search Qdrant") from exc
        return [
            VectorHit(id=uuid.UUID(str(point.id)), score=float(point.score))
            for point in response.points
        ]
