import logging
from typing import TypedDict, cast

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from app.agent.model import InvestigationModel
from app.agent.tools import ControlledToolset
from app.config import Settings
from app.schemas.investigation import (
    CitationResponse,
    InvestigationPlan,
    InvestigationResponse,
    SufficiencyDecision,
    TerminationReason,
    ToolRequest,
    ToolTraceResponse,
)

logger = logging.getLogger(__name__)


class AgentOutputValidationError(RuntimeError):
    pass


class AgentStepLimitError(RuntimeError):
    pass


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    tool: str
    title: str
    data: dict[str, object]
    citation: CitationResponse | None = None

    def prompt_value(self) -> dict[str, object]:
        value = self.model_dump(mode="json", exclude={"citation"})
        value["citation"] = self.citation.model_dump(mode="json") if self.citation else None
        return value


class InvestigationState(TypedDict, total=False):
    question: str
    plan: InvestigationPlan
    pending_calls: list[ToolRequest]
    evidence: list[EvidenceRecord]
    tool_trace: list[ToolTraceResponse]
    steps_taken: int
    sufficient: bool
    evaluation_reason: str
    termination_reason: TerminationReason
    answer: str
    citation_ids: list[str]


class InvestigationAgent:
    def __init__(
        self,
        settings: Settings,
        model: InvestigationModel,
        tools: ControlledToolset,
    ) -> None:
        self.settings = settings
        self.model = model
        self.tools = tools
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(InvestigationState)
        builder.add_node("plan", self._plan)
        builder.add_node("tools", self._execute_tools)
        builder.add_node("evaluate", self._evaluate)
        builder.add_node("synthesize", self._synthesize)
        builder.add_edge(START, "plan")
        builder.add_edge("plan", "tools")
        builder.add_edge("tools", "evaluate")
        builder.add_conditional_edges(
            "evaluate",
            self._route_after_evaluation,
            {"tools": "tools", "synthesize": "synthesize"},
        )
        builder.add_edge("synthesize", END)
        return builder.compile(name="repolens-investigation")

    def _plan(self, state: InvestigationState) -> dict[str, object]:
        plan = self.model.plan(state["question"], self.tools.repository_context())
        return {"plan": plan, "pending_calls": plan.tool_calls}

    def _execute_tools(self, state: InvestigationState) -> dict[str, object]:
        step = state.get("steps_taken", 0) + 1
        evidence = list(state.get("evidence", []))
        traces = list(state.get("tool_trace", []))
        pending = state.get("pending_calls", [])
        allowed = pending[: self.settings.agent_max_tool_calls_per_step]
        rejected = pending[self.settings.agent_max_tool_calls_per_step :]

        for request in rejected:
            traces.append(
                ToolTraceResponse(
                    call_id=f"call-{len(traces) + 1}",
                    step=step,
                    tool=request.tool,
                    arguments=request.arguments,
                    purpose=request.purpose,
                    status="error",
                    error="Configured per-step tool-call limit exceeded",
                )
            )

        for request in allowed:
            call_id = f"call-{len(traces) + 1}"
            evidence_ids: list[str] = []
            try:
                result = self.tools.execute(request)
                for candidate in result.evidence:
                    if len(evidence) >= self.settings.agent_max_evidence_items:
                        break
                    evidence_id = f"evidence-{len(evidence) + 1}"
                    citation = self.tools.citation(candidate, evidence_id)
                    evidence.append(
                        EvidenceRecord(
                            id=evidence_id,
                            tool=request.tool,
                            title=candidate.title,
                            data=candidate.data,
                            citation=citation,
                        )
                    )
                    evidence_ids.append(evidence_id)
                trace = ToolTraceResponse(
                    call_id=call_id,
                    step=step,
                    tool=request.tool,
                    arguments=request.arguments,
                    purpose=request.purpose,
                    status="success",
                    summary=result.summary,
                    evidence_ids=evidence_ids,
                )
            except Exception as exc:  # A tool failure must not abort the investigation.
                trace = ToolTraceResponse(
                    call_id=call_id,
                    step=step,
                    tool=request.tool,
                    arguments=request.arguments,
                    purpose=request.purpose,
                    status="error",
                    error=str(exc)[:500] or exc.__class__.__name__,
                )
            traces.append(trace)
            logger.info(
                "investigation_tool_call tool=%s status=%s step=%s evidence=%s",
                trace.tool,
                trace.status,
                step,
                len(trace.evidence_ids),
            )
        return {
            "evidence": evidence,
            "tool_trace": traces,
            "steps_taken": step,
            "pending_calls": [],
        }

    def _evaluate(self, state: InvestigationState) -> dict[str, object]:
        steps_taken = state["steps_taken"]
        remaining_steps = max(0, self.settings.agent_max_steps - steps_taken)
        decision: SufficiencyDecision = self.model.evaluate(
            state["question"],
            state["plan"],
            [item.prompt_value() for item in state.get("evidence", [])],
            [item.model_dump(mode="json") for item in state.get("tool_trace", [])],
            remaining_steps,
        )
        update: dict[str, object] = {
            "sufficient": decision.sufficient,
            "evaluation_reason": decision.reasoning,
            "pending_calls": decision.additional_tool_calls,
        }
        if decision.sufficient:
            update["termination_reason"] = "completed"
        elif steps_taken >= self.settings.agent_max_steps:
            update["termination_reason"] = "max_steps"
            update["pending_calls"] = []
        elif not decision.additional_tool_calls:
            update["termination_reason"] = "no_more_tools"
        return update

    @staticmethod
    def _route_after_evaluation(state: InvestigationState) -> str:
        return "synthesize" if state.get("termination_reason") else "tools"

    def _synthesize(self, state: InvestigationState) -> dict[str, object]:
        evidence = state.get("evidence", [])
        draft = self.model.synthesize(
            state["question"],
            self.tools.repository_context(),
            [item.prompt_value() for item in evidence],
        )
        citations = {item.id: item.citation for item in evidence if item.citation is not None}
        unknown_ids = [item for item in draft.citation_ids if item not in citations]
        if unknown_ids:
            raise AgentOutputValidationError(
                f"Model returned unknown or non-citable evidence IDs: {unknown_ids}"
            )
        if citations and not draft.citation_ids:
            raise AgentOutputValidationError(
                "Model answer omitted citations despite having source evidence"
            )
        citation_ids = list(dict.fromkeys(draft.citation_ids))
        return {"answer": draft.answer, "citation_ids": citation_ids}

    def investigate(self, question: str) -> InvestigationResponse:
        initial: InvestigationState = {
            "question": question,
            "evidence": [],
            "tool_trace": [],
            "steps_taken": 0,
        }
        try:
            final = cast(
                InvestigationState,
                self.graph.invoke(
                    initial,
                    config={"recursion_limit": self.settings.agent_max_steps * 2 + 5},
                ),
            )
        except GraphRecursionError as exc:
            raise AgentStepLimitError("LangGraph recursion limit reached") from exc

        evidence_by_id = {item.id: item for item in final.get("evidence", [])}
        citations = [
            evidence_by_id[item].citation
            for item in final["citation_ids"]
            if evidence_by_id[item].citation is not None
        ]
        return InvestigationResponse(
            repository_id=self.tools.repository.id,
            snapshot_id=self.tools.snapshot.id,
            commit_sha=self.tools.snapshot.commit_sha,
            question=question,
            plan=final["plan"],
            answer=final["answer"],
            citations=citations,
            tool_trace=final.get("tool_trace", []),
            steps_taken=final.get("steps_taken", 0),
            termination_reason=final["termination_reason"],
        )
