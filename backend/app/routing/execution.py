import re

from app.agent.model import InvestigationModel
from app.agent.tools import ControlledToolset
from app.agent.workflow import InvestigationAgent
from app.config import Settings
from app.routing.service import RouteStrategy, RoutingDecision
from app.schemas.investigation import (
    RoutedQueryResponse,
    SearchCodeArguments,
    ToolRequest,
    ToolTraceResponse,
)


class RoutedQueryService:
    def __init__(self, settings: Settings, tools: ControlledToolset) -> None:
        self.settings = settings
        self.tools = tools

    def execute(
        self,
        question: str,
        decision: RoutingDecision,
        model: InvestigationModel | None = None,
    ) -> RoutedQueryResponse:
        if decision.strategy is RouteStrategy.FULL_INVESTIGATION:
            if model is None:
                raise RuntimeError("An investigation model is required for this query route")
            investigation = InvestigationAgent(self.settings, model, self.tools).investigate(
                question
            )
            return RoutedQueryResponse(
                repository_id=investigation.repository_id,
                snapshot_id=investigation.snapshot_id,
                commit_sha=investigation.commit_sha,
                question=question,
                routing=decision.model_dump(mode="json"),
                answer=investigation.answer,
                citations=investigation.citations,
                tool_trace=investigation.tool_trace,
                model_runs=investigation.model_runs,
                investigation=investigation,
            )
        if decision.strategy is RouteStrategy.REPOSITORY_METADATA:
            request = ToolRequest(
                tool="repository_metadata",
                arguments={},
                purpose="Answer snapshot metadata question",
            )
        elif decision.strategy is RouteStrategy.DIRECT_SYMBOL_LOOKUP:
            symbol_name = self._extract_symbol_name(question)
            if symbol_name is None:
                request = ToolRequest(
                    tool="search_code",
                    arguments=SearchCodeArguments(query=question, mode="hybrid").model_dump(
                        mode="json"
                    ),
                    purpose="Find the symbol mentioned in the question",
                )
            else:
                request = ToolRequest(
                    tool="lookup_symbol",
                    arguments={"name": symbol_name},
                    purpose="Look up the requested symbol",
                )
        else:
            request = ToolRequest(
                tool="search_code",
                arguments=SearchCodeArguments(query=question, mode="hybrid").model_dump(
                    mode="json"
                ),
                purpose="Retrieve code evidence for the question",
            )
        result = self.tools.execute(request)
        citations = [
            citation
            for index, candidate in enumerate(result.evidence, start=1)
            if (citation := self.tools.citation(candidate, f"evidence-{index}")) is not None
        ]
        trace = ToolTraceResponse(
            call_id="route-1",
            step=0,
            tool=request.tool,
            arguments=request.arguments,
            purpose=request.purpose,
            status="success",
            summary=result.summary,
            evidence_ids=[citation.id for citation in citations],
        )
        answer = result.summary
        if request.tool == "repository_metadata" and result.evidence:
            answer = f"Repository snapshot metadata: {result.evidence[0].data}"
        return RoutedQueryResponse(
            repository_id=self.tools.repository.id,
            snapshot_id=self.tools.snapshot.id,
            commit_sha=self.tools.snapshot.commit_sha,
            question=question,
            routing=decision.model_dump(mode="json"),
            answer=answer,
            citations=citations,
            tool_trace=[trace],
        )

    @staticmethod
    def _extract_symbol_name(question: str) -> str | None:
        quoted = re.search(r"[`']([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)[`']", question)
        if quoted:
            return quoted.group(1)
        dotted = re.search(r"\b([A-Za-z_]\w*\.[A-Za-z_]\w*)\b", question)
        return dotted.group(1) if dotted else None
