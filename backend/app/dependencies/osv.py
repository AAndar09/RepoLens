from typing import Protocol

import httpx

from app.config import Settings


class OsvError(RuntimeError):
    pass


class VulnerabilityProvider(Protocol):
    def query(self, ecosystem: str, package: str, version: str) -> list[dict[str, object]]: ...


class OsvClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.osv_api_url.rstrip("/")
        self.timeout = settings.osv_timeout_seconds
        self.max_results = settings.osv_max_results_per_dependency

    def query(self, ecosystem: str, package: str, version: str) -> list[dict[str, object]]:
        request_payload: dict[str, object] = {
            "package": {"ecosystem": ecosystem, "name": package},
            "version": version,
        }
        collected: list[dict[str, object]] = []
        seen_tokens: set[str] = set()
        try:
            while len(collected) < self.max_results:
                response = httpx.post(
                    f"{self.base_url}/v1/query",
                    json=request_payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                vulnerabilities = payload.get("vulns", [])
                if not isinstance(vulnerabilities, list):
                    raise ValueError("OSV response 'vulns' was not a list")
                collected.extend(item for item in vulnerabilities if isinstance(item, dict))
                token = payload.get("next_page_token")
                if not token or not isinstance(token, str) or token in seen_tokens:
                    break
                seen_tokens.add(token)
                request_payload["page_token"] = token
            return collected[: self.max_results]
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise OsvError(f"OSV query failed for {package} {version}") from exc
