"""Manually test one configured LLM provider without running the API server."""

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.llm.base import LLMMessage, LLMProviderError
from app.llm.factory import create_provider


class SmokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    provider_summary: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", help="Override REPOLENS_LLM_PROVIDER")
    parser.add_argument("--model", help="Override REPOLENS_LLM_MODEL")
    args = parser.parse_args()
    settings = Settings(_env_file=Path(__file__).resolve().parents[2] / ".env")
    provider_name = args.provider or settings.llm_provider
    model = args.model or settings.llm_model
    provider = create_provider(settings, provider_name, model)
    try:
        value, result = provider.invoke_structured(
            [
                LLMMessage("system", "Return the requested small structured result."),
                LLMMessage("user", f"Report status ok and identify {provider_name}."),
            ],
            SmokeResponse,
            max_output_tokens=100,
        )
    except LLMProviderError as exc:
        print(json.dumps({"provider": provider_name, "model": model, "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {
                "provider": result.provider,
                "model": result.model,
                "duration_ms": result.duration_ms,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "response": value.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
