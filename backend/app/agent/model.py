import json
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.schemas.investigation import (
    AnswerDraft,
    InvestigationPlan,
    SufficiencyDecision,
)


class InvestigationModelError(RuntimeError):
    pass


class InvestigationModelConfigurationError(InvestigationModelError):
    pass


class InvestigationModel(Protocol):
    @property
    def name(self) -> str: ...

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


OutputModel = TypeVar("OutputModel", bound=BaseModel)


class OllamaInvestigationModel:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.agent_model_timeout_seconds

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def _structured(
        self,
        output_type: type[OutputModel],
        system_prompt: str,
        payload: dict[str, object],
    ) -> OutputModel:
        schema = output_type.model_json_schema()
        user_prompt = (
            f"Input:\n{json.dumps(payload, default=str)}\n\n"
            f"Return JSON matching this schema exactly:\n{json.dumps(schema)}"
        )
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            return output_type.model_validate_json(content)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise InvestigationModelError(
                f"The configured Ollama model could not produce {output_type.__name__}"
            ) from exc

    def plan(self, question: str, repository_context: dict[str, object]) -> InvestigationPlan:
        return self._structured(
            InvestigationPlan,
            (
                "You plan a code investigation. Use only the listed controlled tools. "
                "Start with the smallest useful set of calls and never request shell, filesystem, "
                "network, or infrastructure access. Tool argument schemas are included in context."
            ),
            {"question": question, "repository": repository_context},
        )

    def evaluate(
        self,
        question: str,
        plan: InvestigationPlan,
        evidence: list[dict[str, object]],
        tool_trace: list[dict[str, object]],
        remaining_steps: int,
    ) -> SufficiencyDecision:
        return self._structured(
            SufficiencyDecision,
            (
                "Evaluate whether the evidence directly answers the repository question. "
                "If more evidence is necessary, request only controlled tools and explain why. "
                "Do not repeat failed calls unchanged."
            ),
            {
                "question": question,
                "plan": plan.model_dump(mode="json"),
                "evidence": evidence,
                "tool_trace": tool_trace,
                "remaining_steps": remaining_steps,
            },
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
                "repository": repository_context,
                "evidence": evidence,
            },
        )


def create_investigation_model(settings: Settings) -> InvestigationModel:
    if settings.agent_model_provider == "ollama":
        return OllamaInvestigationModel(settings)
    raise InvestigationModelConfigurationError(
        f"Unsupported investigation model provider: {settings.agent_model_provider}"
    )
