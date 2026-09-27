import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.agent.tools import ControlledToolset
from app.agent.workflow import EvidenceRecord, InvestigationAgent
from app.api.routes.investigations import get_investigation_model
from app.api.routes.repositories import get_embedding_provider, get_vector_store
from app.config import Settings
from app.main import app
from app.models.code_symbol import CodeSymbol, SymbolKind
from app.models.repository import Repository, RepositoryStatus
from app.models.snapshot import RepositorySnapshot, SnapshotStatus
from app.models.source_file import FileParseStatus, SourceFile
from app.retrieval.embeddings import HashingEmbeddingProvider
from app.retrieval.service import RetrievalIndexer
from app.retrieval.vector_store import VectorHit, VectorPoint
from app.schemas.investigation import (
    AnswerDraft,
    InvestigationPlan,
    SufficiencyDecision,
    ToolRequest,
)


class MemoryVectors:
    def __init__(self) -> None:
        self.points: dict[uuid.UUID, list[VectorPoint]] = {}

    def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        del collection_name, dimensions

    def replace_snapshot(
        self,
        collection_name: str,
        snapshot_id: uuid.UUID,
        points: list[VectorPoint],
    ) -> None:
        del collection_name
        self.points[snapshot_id] = points

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
        del collection_name, vector
        hits = []
        for point in self.points.get(snapshot_id, []):
            payload = point.payload
            if filepath and payload["filepath"] != filepath:
                continue
            if symbol_kind and payload["symbol_kind"] != symbol_kind:
                continue
            if language and payload["language"] != language:
                continue
            hits.append(VectorHit(point.id, 0.75))
        return hits[:limit]


def _seed(
    session: Session,
) -> tuple[Repository, RepositorySnapshot, SourceFile, CodeSymbol]:
    repository = Repository(
        github_url="https://github.com/acme/agent-demo",
        owner="acme",
        name="agent-demo",
        status=RepositoryStatus.READY,
    )
    snapshot = RepositorySnapshot(
        repository=repository,
        branch="main",
        commit_sha="d" * 40,
        status=SnapshotStatus.READY,
        file_count=1,
        parsed_file_count=1,
        symbol_count=2,
    )
    content = "def target(value: int) -> int:\n    result = value + 1\n    return result\n"
    source_file = SourceFile(
        snapshot=snapshot,
        path="src/demo.py",
        module_name="src.demo",
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content),
        line_count=3,
        parse_status=FileParseStatus.PARSED,
        content=content,
    )
    module = CodeSymbol(
        source_file=source_file,
        kind=SymbolKind.MODULE,
        name="demo",
        qualified_name="src.demo",
        start_line=1,
        end_line=3,
    )
    function = CodeSymbol(
        source_file=source_file,
        parent=module,
        kind=SymbolKind.FUNCTION,
        name="target",
        qualified_name="src.demo.target",
        start_line=1,
        end_line=3,
    )
    session.add_all([repository, snapshot, source_file, module, function])
    session.commit()
    return repository, snapshot, source_file, function


class MultiStepModel:
    name = "test:multi-step"

    def plan(self, question, repository_context):
        del question, repository_context
        return InvestigationPlan(
            objective="Understand target and its containment",
            rationale="Locate the symbol before reading and traversing it",
            tool_calls=[
                ToolRequest(
                    tool="lookup_symbol",
                    arguments={"name": "target"},
                    purpose="Locate the target symbol",
                )
            ],
        )

    def evaluate(self, question, plan, evidence, tool_trace, remaining_steps):
        del question, plan, tool_trace, remaining_steps
        if len(evidence) == 1:
            symbol_id = evidence[0]["data"]["symbol_id"]
            return SufficiencyDecision(
                sufficient=False,
                reasoning="Need the complete source and structural parent",
                additional_tool_calls=[
                    ToolRequest(
                        tool="read_source",
                        arguments={"filepath": "src/demo.py", "start_line": 1, "end_line": 3},
                        purpose="Read the implementation",
                    ),
                    ToolRequest(
                        tool="structural_lookup",
                        arguments={
                            "operation": "symbol_containment",
                            "entity_id": symbol_id,
                        },
                        purpose="Confirm symbol containment",
                    ),
                ],
            )
        return SufficiencyDecision(
            sufficient=True,
            reasoning="Implementation and structure are both available",
        )

    def synthesize(self, question, repository_context, evidence):
        del question, repository_context
        citation_ids = [item["id"] for item in evidence if item["citation"]]
        return AnswerDraft(
            answer="The target function increments its input and belongs to src.demo.",
            citation_ids=citation_ids,
        )


class FailureTolerantModel:
    name = "test:failure"

    def plan(self, question, repository_context):
        del question, repository_context
        return InvestigationPlan(
            objective="Try a missing file and load metadata",
            rationale="Exercise independent tool failure handling",
            tool_calls=[
                ToolRequest(
                    tool="read_source",
                    arguments={"filepath": "missing.py"},
                    purpose="Attempt the requested file",
                ),
                ToolRequest(
                    tool="repository_metadata",
                    arguments={},
                    purpose="Retain useful repository context",
                ),
            ],
        )

    def evaluate(self, question, plan, evidence, tool_trace, remaining_steps):
        del question, plan, evidence, tool_trace, remaining_steps
        return SufficiencyDecision(sufficient=True, reasoning="Failure is transparent")

    def synthesize(self, question, repository_context, evidence):
        del question, repository_context, evidence
        return AnswerDraft(
            answer="The requested file was unavailable; repository metadata was still inspected.",
            citation_ids=[],
        )


class LoopingModel(FailureTolerantModel):
    name = "test:loop"

    def plan(self, question, repository_context):
        del question, repository_context
        return InvestigationPlan(
            objective="Repeated metadata lookup",
            rationale="Exercise step termination",
            tool_calls=[
                ToolRequest(
                    tool="repository_metadata",
                    arguments={},
                    purpose="Inspect metadata",
                )
            ],
        )

    def evaluate(self, question, plan, evidence, tool_trace, remaining_steps):
        del question, plan, evidence, tool_trace, remaining_steps
        return SufficiencyDecision(
            sufficient=False,
            reasoning="Request another lookup",
            additional_tool_calls=[
                ToolRequest(
                    tool="repository_metadata",
                    arguments={},
                    purpose="Inspect metadata again",
                )
            ],
        )


def _tools(session, settings, repository, snapshot, vectors, embeddings):
    return ControlledToolset(session, settings, repository, snapshot, vectors, embeddings)


def test_agent_performs_multiple_lookup_rounds_with_snapshot_citations(
    session_factory,
) -> None:
    settings = Settings(_env_file=None, embedding_dimensions=16)
    vectors = MemoryVectors()
    embeddings = HashingEmbeddingProvider(16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed(session)
        response = InvestigationAgent(
            settings,
            MultiStepModel(),
            _tools(session, settings, repository, snapshot, vectors, embeddings),
        ).investigate("What does target do and where is it contained?")

    assert response.steps_taken == 2
    assert response.termination_reason == "completed"
    assert [trace.tool for trace in response.tool_trace] == [
        "lookup_symbol",
        "read_source",
        "structural_lookup",
    ]
    assert all(trace.status == "success" for trace in response.tool_trace)
    assert response.citations
    assert all(item.commit_sha == "d" * 40 for item in response.citations)
    assert all("/blob/" + "d" * 40 in item.source_url for item in response.citations)


def test_evaluation_evidence_keeps_identity_but_bounds_large_tool_data() -> None:
    record = EvidenceRecord(
        id="evidence-1",
        tool="read_source",
        title="src/demo.py",
        data={"content": "x" * 2_000},
    )

    value = record.evaluation_prompt_value(100)

    assert value["id"] == "evidence-1"
    assert value["data"]["truncated"] is True
    assert len(value["data"]["preview"]) == 50


def test_planning_context_uses_compact_tool_guidance(session_factory) -> None:
    settings = Settings(_env_file=None, embedding_dimensions=16)
    vectors = MemoryVectors()
    embeddings = HashingEmbeddingProvider(16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed(session)
        context = _tools(
            session, settings, repository, snapshot, vectors, embeddings
        ).planning_context()

    assert context["owner"] == "acme"
    assert "arguments_schema" not in context["available_actions"]["search_code"]


def test_tool_failure_is_observable_and_does_not_abort(session_factory) -> None:
    settings = Settings(_env_file=None, embedding_dimensions=16)
    vectors = MemoryVectors()
    embeddings = HashingEmbeddingProvider(16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed(session)
        response = InvestigationAgent(
            settings,
            FailureTolerantModel(),
            _tools(session, settings, repository, snapshot, vectors, embeddings),
        ).investigate("Read a file that is missing")

    assert [trace.status for trace in response.tool_trace] == ["error", "success"]
    assert "not found" in response.tool_trace[0].error.lower()
    assert response.answer.startswith("The requested file was unavailable")


def test_agent_stops_at_configured_max_steps(session_factory) -> None:
    settings = Settings(_env_file=None, embedding_dimensions=16, agent_max_steps=2)
    vectors = MemoryVectors()
    embeddings = HashingEmbeddingProvider(16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed(session)
        response = InvestigationAgent(
            settings,
            LoopingModel(),
            _tools(session, settings, repository, snapshot, vectors, embeddings),
        ).investigate("Keep looking forever")

    assert response.steps_taken == 2
    assert response.termination_reason == "max_steps"
    assert len(response.tool_trace) == 2


def test_search_code_tool_wraps_hybrid_retrieval(session_factory) -> None:
    settings = Settings(_env_file=None, embedding_dimensions=16)
    vectors = MemoryVectors()
    embeddings = HashingEmbeddingProvider(16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed(session)
        RetrievalIndexer(session, settings, vectors, embeddings).index_snapshot(snapshot)
        result = _tools(session, settings, repository, snapshot, vectors, embeddings).execute(
            ToolRequest(
                tool="search_code",
                arguments={"query": "increment input", "mode": "hybrid"},
                purpose="Find the implementation",
            )
        )

    assert result.evidence
    assert result.evidence[0].filepath == "src/demo.py"


def test_investigation_api_returns_structured_trace(client: TestClient, session_factory) -> None:
    vectors = MemoryVectors()
    embeddings = HashingEmbeddingProvider(16)
    with session_factory() as session:
        repository, snapshot, _, _ = _seed(session)
        repository_id = repository.id
        snapshot_id = snapshot.id

    app.dependency_overrides[get_investigation_model] = lambda: MultiStepModel()
    app.dependency_overrides[get_vector_store] = lambda: vectors
    app.dependency_overrides[get_embedding_provider] = lambda: embeddings
    response = client.post(
        f"/api/v1/repositories/{repository_id}/snapshots/{snapshot_id}/investigations",
        json={"question": "What does target do and where is it contained?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["termination_reason"] == "completed"
    assert len(body["tool_trace"]) == 3
    assert body["citations"][0]["snapshot_id"] == str(snapshot_id)
