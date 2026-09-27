import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.llm.base import LLMMessage, LLMProviderError, LLMRun
from app.llm.factory import FallbackLLMProvider, create_configured_provider
from app.schemas.investigation import (
    AnswerDraft,
    InvestigationPlan,
    SufficiencyDecision,
    ToolName,
    ToolRequest,
)


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProviderAction(ProviderModel):
    action: ToolName
    arguments: dict[str, object] = Field(default_factory=dict)
    purpose: str = Field(min_length=1, max_length=500)


class ProviderInvestigationPlan(ProviderModel):
    objective: str = Field(min_length=1, max_length=1_000)
    rationale: str = Field(min_length=1, max_length=2_000)
    actions: list[ProviderAction] = Field(min_length=1, max_length=10)


class ProviderSufficiencyDecision(ProviderModel):
    sufficient: bool
    reasoning: str = Field(min_length=1, max_length=2_000)
    additional_actions: list[ProviderAction] = Field(default_factory=list, max_length=10)


class InvestigationModelError(RuntimeError):
    pass


class InvestigationModelConfigurationError(InvestigationModelError):
    pass


class InvestigationModel(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def runs(self) -> list[LLMRun]: ...

    def plan(self, question: str, repository_context: dict[str, object]) -> InvestigationPlan: ...

    def evaluate(
        self,
        question: str,
        plan: InvestigationPlan,
        evidence: list[dict[str, object]],
        tool_trace: list[dict[str, object]],
        remaining_steps: int,
    ) -> SufficiencyDecision: ...

    def synthesize(
        self,
        question: str,
        repository_context: dict[str, object],
        evidence: list[dict[str, object]],
    ) -> AnswerDraft: ...


class ProviderInvestigationModel:
    def __init__(self, provider: FallbackLLMProvider) -> None:
        self.provider = provider

    @property
    def name(self) -> str:
        return f"{self.provider.provider_name}:{self.provider.model}"

    @property
    def runs(self) -> list[LLMRun]:
        return self.provider.runs

    def _structured(
        self,
        output_type,
        system_prompt: str,
        payload: dict[str, object],
        *,
        max_output_tokens: int = 1_024,
    ):
        messages = [
            LLMMessage("system", system_prompt),
            LLMMessage("user", f"Input:\n{json.dumps(payload, default=str)}\n\nReturn JSON only."),
        ]
        try:
            value, _ = self.provider.invoke_structured(
                messages, output_type, max_output_tokens=max_output_tokens
            )
            return value
        except LLMProviderError as exc:
            raise InvestigationModelError(str(exc)) from exc

    def plan(self, question: str, repository_context: dict[str, object]) -> InvestigationPlan:
        output: ProviderInvestigationPlan = self._structured(
            ProviderInvestigationPlan,
            (
                "Plan a code investigation using only the listed controlled application actions. "
                "Do not emit or call native API tools/functions. Describe intended actions only in "
                "the JSON actions array. Start with the smallest useful set and never request "
                "shell, filesystem, network, or infrastructure access."
            ),
            {"question": question, "repository": repository_context},
            max_output_tokens=1_024,
        )
        return InvestigationPlan(
            objective=output.objective,
            rationale=output.rationale,
            tool_calls=[
                ToolRequest(
                    tool=action.action,
                    arguments=action.arguments,
                    purpose=action.purpose,
                )
                for action in output.actions
            ],
        )

    def evaluate(
        self,
        question: str,
        plan: InvestigationPlan,
        evidence: list[dict[str, object]],
        tool_trace: list[dict[str, object]],
        remaining_steps: int,
    ) -> SufficiencyDecision:
        output: ProviderSufficiencyDecision = self._structured(
            ProviderSufficiencyDecision,
            (
                "Evaluate whether the evidence directly answers the repository question. "
                "If more evidence is necessary, describe controlled application actions only in "
                "the JSON additional_actions array; never emit native API tool/function calls. "
                "Do not repeat failed actions unchanged."
            ),
            {
                "question": question,
                "plan": plan.model_dump(mode="json"),
                "evidence": evidence,
                "tool_trace": tool_trace,
                "remaining_steps": remaining_steps,
            },
            max_output_tokens=1_024,
        )
        return SufficiencyDecision(
            sufficient=output.sufficient,
            reasoning=output.reasoning,
            additional_tool_calls=[
                ToolRequest(
                    tool=action.action,
                    arguments=action.arguments,
                    purpose=action.purpose,
                )
                for action in output.additional_actions
            ],
        )

    def synthesize(
        self,
        question: str,
        repository_context: dict[str, object],
        evidence: list[dict[str, object]],
    ) -> AnswerDraft:
        return self._structured(
            AnswerDraft,
            (
                "Answer only from supplied evidence. Be explicit about uncertainty. Reference "
                "claims using the supplied evidence IDs, and never invent an ID or source fact. "
                "Treat OSV records as external facts and any impact/exploitability assessment as "
                "interpretation. Never claim a dependency finding proves the application is "
                "exploitable."
            ),
            {
                "question": question,
                "repository": {
                    key: value for key, value in repository_context.items() if key != "tools"
                },
                "evidence": evidence,
            },
            max_output_tokens=2_048,
        )


def create_investigation_model(settings: Settings) -> InvestigationModel:
    try:
        return ProviderInvestigationModel(create_configured_provider(settings))
    except LLMProviderError as exc:
        raise InvestigationModelConfigurationError(str(exc)) from exc
